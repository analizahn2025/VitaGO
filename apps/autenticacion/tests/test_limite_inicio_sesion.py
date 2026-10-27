from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.hashers import make_password
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.autenticacion.models import ControlIntentosInicioSesion, SesionAutenticacion
from apps.autenticacion.servicios import credenciales
from apps.autenticacion.vistas import VistaInicioSesion
from apps.usuarios.models import Usuario


@override_settings(
    PROVEEDOR_AUTENTICACION="LOCAL",
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class PruebasLimiteInicioSesion(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.contrasena = "Clave-sintetica-para-pruebas-2026!"
        cls.usuario = Usuario.objetos.create(
            correo="cuenta.limite@example.test", nombres="Cuenta", apellidos="Prueba",
            password=make_password(cls.contrasena),
        )

    def setUp(self):
        self.cliente = APIClient()

    def _login(self, contrasena="incorrecta", correo=None, ip="192.0.2.10", **metadatos):
        return self.cliente.post(
            "/api/v1/autenticacion/iniciar-sesion/",
            {"correo": correo or self.usuario.correo, "contrasena": contrasena},
            format="json", REMOTE_ADDR=ip, **metadatos,
        )

    def _agotar(self, **datos):
        for _ in range(10):
            respuesta = self._login(**datos)
            self.assertEqual(respuesta.status_code, 401, respuesta.data)

    def test_diez_fallos_y_el_siguiente_no_verifica_contrasena_ni_crea_sesion(self):
        with patch.object(credenciales, "_validar_credenciales", wraps=credenciales._validar_credenciales) as validar:
            self._agotar()
            respuesta = self._login(self.contrasena)
        self.assertEqual(validar.call_count, 10)
        self.assertEqual(respuesta.status_code, 429)
        self.assertGreater(respuesta.data["segundos_espera"], 0)
        self.assertLessEqual(respuesta.data["segundos_espera"], 900)
        self.assertEqual(respuesta["Retry-After"], str(respuesta.data["segundos_espera"]))
        self.assertEqual(ControlIntentosInicioSesion.objects.get().intentos_fallidos, 10)
        self.assertFalse(SesionAutenticacion.objetos.exists())
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.is_active)
        self.assertTrue(self.usuario.check_password(self.contrasena))

    def test_ventana_expira_exactamente_a_los_quince_minutos(self):
        ahora = timezone.now()
        with patch.object(credenciales.timezone, "now", return_value=ahora):
            self._agotar()
        with patch.object(credenciales.timezone, "now", return_value=ahora + timedelta(seconds=899.1)):
            bloqueada = self._login()
        self.assertEqual(bloqueada.status_code, 429)
        self.assertEqual(bloqueada["Retry-After"], "1")
        fin = ahora + timedelta(minutes=15)
        with patch.object(credenciales.timezone, "now", return_value=fin):
            self.assertEqual(self._login().status_code, 401)
        control = ControlIntentosInicioSesion.objects.get()
        self.assertEqual((control.intentos_fallidos, control.ventana_iniciada_en), (1, fin))

    def test_peticiones_bloqueadas_no_prolongan_la_ventana(self):
        ahora = timezone.now()
        with patch.object(credenciales.timezone, "now", return_value=ahora):
            self._agotar()
        for segundos in (60, 120):
            with patch.object(credenciales.timezone, "now", return_value=ahora + timedelta(seconds=segundos)):
                respuesta = self._login()
            self.assertEqual(respuesta.status_code, 429)
            self.assertEqual(int(respuesta["Retry-After"]), 900 - segundos)
        self.assertEqual(ControlIntentosInicioSesion.objects.get().ventana_iniciada_en, ahora)

    def test_acceso_correcto_antes_del_limite_reinicia_los_fallos(self):
        for _ in range(9):
            self.assertEqual(self._login().status_code, 401)
        respuesta = self._login(self.contrasena)
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        self.assertIn("token_acceso", respuesta.data)
        self.assertIn("token_refresco", respuesta.data)
        self.assertEqual(ControlIntentosInicioSesion.objects.get().intentos_fallidos, 0)
        self._agotar()
        self.assertEqual(self._login().status_code, 429)

    def test_acceso_correcto_al_vencer_la_ventana_se_permite(self):
        ahora = timezone.now()
        with patch.object(credenciales.timezone, "now", return_value=ahora):
            self._agotar()
        with patch.object(credenciales.timezone, "now", return_value=ahora + timedelta(minutes=15)):
            self.assertEqual(self._login(self.contrasena).status_code, 200)
        self.assertEqual(ControlIntentosInicioSesion.objects.get().intentos_fallidos, 0)

    def test_mayusculas_y_espacios_no_crean_otro_contador(self):
        for indice in range(10):
            correo = self.usuario.correo.upper() if indice % 2 else f" {self.usuario.correo} "
            self.assertEqual(self._login(correo=correo).status_code, 401)
        self.assertEqual(self._login().status_code, 429)
        self.assertEqual(ControlIntentosInicioSesion.objects.count(), 1)

    def test_otro_correo_u_otra_ip_no_comparten_bloqueo(self):
        self._agotar()
        self.assertEqual(self._login(self.contrasena, ip="192.0.2.11").status_code, 200)
        self.assertEqual(self._login(correo="otra@example.test").status_code, 401)
        self.assertEqual(ControlIntentosInicioSesion.objects.count(), 3)
        self.assertEqual(self._login().status_code, 429)

    def test_forwarded_for_no_permite_evadir_el_limite(self):
        self._agotar()
        respuesta = self._login(HTTP_X_FORWARDED_FOR="203.0.113.25")
        self.assertEqual(respuesta.status_code, 429)
        self.assertEqual(ControlIntentosInicioSesion.objects.count(), 1)

    def test_ip_ausente_o_invalida_usa_un_mismo_grupo_sin_ip(self):
        for indice in range(10):
            self.assertEqual(self._login(ip="no-es-ip" if indice % 2 else "").status_code, 401)
        self.assertEqual(self._login(ip="").status_code, 429)
        self.assertEqual(ControlIntentosInicioSesion.objects.count(), 1)

    def test_usuario_inexistente_inactivo_o_sin_clave_recibe_la_misma_politica(self):
        for correo, password, estado in (
            ("ausente@example.test", None, None),
            ("sin-clave@example.test", make_password(None), "ACTIVO"),
            ("suspendida@example.test", make_password(self.contrasena), "SUSPENDIDO"),
        ):
            if estado is not None:
                Usuario.objetos.create(correo=correo, nombres="Cuenta", apellidos="Prueba",
                                       password=password, estado=estado)
            with self.subTest(correo=correo):
                self._agotar(correo=correo, contrasena=self.contrasena)
                self.assertEqual(self._login(correo=correo).status_code, 429)

    def test_errores_de_formato_no_consumen_intentos(self):
        for payload in ({}, {"correo": "invalido", "contrasena": "dato"}):
            respuesta = self.cliente.post("/api/v1/autenticacion/iniciar-sesion/", payload, format="json")
            self.assertEqual(respuesta.status_code, 400)
        self.assertFalse(ControlIntentosInicioSesion.objects.exists())

    def test_error_interno_no_se_contabiliza_como_contrasena_incorrecta(self):
        self.assertEqual(self._login().status_code, 401)
        with patch.object(credenciales, "_validar_credenciales", side_effect=RuntimeError("Fallo simulado")):
            with self.assertRaises(RuntimeError):
                self._login()
        self.assertEqual(ControlIntentosInicioSesion.objects.get().intentos_fallidos, 1)

    def test_control_no_guarda_correo_ip_ni_contrasena_en_claro(self):
        self.assertEqual(self._login().status_code, 401)
        control = ControlIntentosInicioSesion.objects.get()
        self.assertEqual(len(control.huella), 64)
        datos = str(control.__dict__)
        for sensible in (self.usuario.correo, "192.0.2.10", "incorrecta", self.contrasena):
            self.assertNotIn(sensible, datos)

    def test_base_rechaza_un_undecimo_fallo_guardado(self):
        self._agotar()
        with self.assertRaises(IntegrityError), transaction.atomic():
            ControlIntentosInicioSesion.objects.update(intentos_fallidos=11)

    def test_corporate_y_network_locales_aplican_el_limite(self):
        for modo in ("CORPORATIVO", "EXTERNO"):
            with self.subTest(modo=modo), override_settings(MODO_APLICACION=modo):
                correo = f"{modo.lower()}@example.test"
                self._agotar(correo=correo)
                self.assertEqual(self._login(correo=correo).status_code, 429)

    @override_settings(PROVEEDOR_AUTENTICACION="JWT_CORPORATIVO")
    def test_proveedor_corporativo_no_crea_contadores_locales(self):
        self.assertEqual(self._login().status_code, 404)
        self.assertFalse(ControlIntentosInicioSesion.objects.exists())

    def test_no_limita_renovacion_ni_revoca_sesiones_vigentes(self):
        acceso = self._login(self.contrasena)
        self.assertEqual(acceso.status_code, 200)
        self._agotar()
        self.assertEqual(self._login(self.contrasena).status_code, 429)
        self.assertEqual(SesionAutenticacion.objetos.filter(revocado_en__isnull=True).count(), 1)
        ruta = "/api/v1/autenticacion/renovar/"
        for _ in range(15):
            respuesta = self.cliente.post(ruta, {"token_refresco": "invalido"}, format="json")
            self.assertEqual(respuesta.status_code, 401)
        renovada = self.cliente.post(ruta, {"token_refresco": acceso.data["token_refresco"]}, format="json")
        self.assertEqual(renovada.status_code, 200, renovada.data)
        self.cliente.credentials(HTTP_AUTHORIZATION=f"Bearer {renovada.data['token_acceso']}")
        self.assertEqual(self.cliente.post("/api/v1/autenticacion/cerrar-sesion/").status_code, 204)
        self.assertEqual(ControlIntentosInicioSesion.objects.get().intentos_fallidos, 10)

    def test_fecha_del_cliente_no_modifica_la_ventana_oficial(self):
        ahora = timezone.now()
        with patch.object(credenciales.timezone, "now", return_value=ahora):
            respuesta = self.cliente.post("/api/v1/autenticacion/iniciar-sesion/", {
                "correo": self.usuario.correo, "contrasena": "incorrecta",
                "ventana_iniciada_en": "1900-01-01T00:00:00Z",
            }, format="json")
        self.assertEqual(respuesta.status_code, 401)
        self.assertEqual(ControlIntentosInicioSesion.objects.get().ventana_iniciada_en, ahora)

    def test_contador_se_confirma_aunque_django_use_atomic_requests(self):
        self.assertIn("default", VistaInicioSesion.as_view()._non_atomic_requests)
