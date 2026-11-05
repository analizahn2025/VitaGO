"""Edición real por HTTP: persistencia, contrato, alcance y validación de campos."""

from decimal import Decimal
from uuid import uuid4

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.geografia.models import Pais
from apps.organizaciones.models import Empresa, Sucursal
from apps.ubicaciones.models import TipoUbicacion, Ubicacion, UbicacionEmpresa
from apps.usuarios.models import Permiso, PermisoRol, Rol, RolUsuario, Usuario


@override_settings(MODO_APLICACION="CORPORATIVO", PROVEEDOR_AUTENTICACION="LOCAL")
class PruebasActualizacionUbicaciones(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pais = Pais.objects.create(iso2="HN", iso3="HND", nombre="Honduras", codigo_telefonico="+504",
            codigo_moneda="HNL", zona_horaria_predeterminada="America/Tegucigalpa")
        cls.empresa = Empresa.objects.create(nombre="Empresa de prueba", pais=cls.pais)
        cls.otra_empresa = Empresa.objects.create(nombre="Empresa ajena", pais=cls.pais)
        cls.tipo = TipoUbicacion.objects.get(codigo="SUCURSAL")
        cls.otro_tipo = TipoUbicacion.objects.get(codigo="OTRO")
        cls.administrador = Usuario.objetos.create(correo="admin.ubicaciones@example.test", nombres="Ana", empresa=cls.empresa)
        cls.superadministrador = Usuario.objetos.create(correo="root.ubicaciones@example.test", nombres="Raíz",
            empresa=cls.empresa, es_superusuario=True)
        RolUsuario.objetos.create(usuario=cls.administrador, rol=Rol.objetos.get(codigo="ADMINISTRADOR_CORPORATIVO"),
            tipo_alcance="EMPRESA", empresa=cls.empresa, asignado_por=cls.superadministrador)
        cls.ubicacion = Ubicacion.objects.create(nombre="Sucursal original", tipo_ubicacion=cls.tipo,
            origen="REGISTRADA_USUARIO", pais=cls.pais, direccion="Dirección original", nivel_administrativo_1="Cortés",
            nivel_administrativo_2="San Pedro Sula", localidad="San Pedro Sula", colonia="Centro",
            latitud=Decimal("15.500000"), longitud=Decimal("-88.030000"), telefono="2222-2222",
            nombre_contacto="Contacto original", instrucciones="Recepción", verificada=True,
            creada_por=cls.superadministrador.pk)
        cls.relacion = UbicacionEmpresa.objects.create(empresa=cls.empresa, ubicacion=cls.ubicacion,
            permite_origen=True, permite_destino=False, estado="PENDIENTE")
        cls.ajena = Ubicacion.objects.create(nombre="Ajena", tipo_ubicacion=cls.tipo, origen="REGISTRADA_USUARIO",
            pais=cls.pais, direccion="Otra dirección", latitud="14.000000", longitud="-87.000000")
        UbicacionEmpresa.objects.create(empresa=cls.otra_empresa, ubicacion=cls.ajena,
            permite_origen=True, permite_destino=True, estado="APROBADO")

    def setUp(self):
        self.cliente = APIClient()
        self.cliente.force_authenticate(self.administrador)
        self.url = reverse("ubicaciones:detalle-ubicacion", args=[self.ubicacion.pk])

    def _patch(self, cambios, *, ubicacion=None, empresa=None):
        url = reverse("ubicaciones:detalle-ubicacion", args=[(ubicacion or self.ubicacion).pk])
        return self.cliente.patch(url, {"empresa_id": str((empresa or self.empresa).pk), **cambios}, format="json")

    def _usuario_con_permiso(self, codigo, *, sucursal=None):
        usuario = Usuario.objetos.create(correo=f"ubicacion-{uuid4().hex}@example.test", nombres="Prueba", empresa=self.empresa)
        rol = Rol.objetos.create(codigo=f"UBI_{uuid4().hex[:8]}", nombre="Rol de prueba",
            permite_alcance_empresa=sucursal is None, permite_alcance_sucursal=sucursal is not None)
        PermisoRol.objetos.create(rol=rol, permiso=Permiso.objetos.get(codigo=codigo))
        RolUsuario.objetos.create(usuario=usuario, rol=rol, tipo_alcance="SUCURSAL" if sucursal else "EMPRESA",
            empresa=self.empresa, sucursal=sucursal, asignado_por=self.superadministrador)
        return usuario

    def test_actualiza_datos_completos_y_devuelve_mismo_objeto_que_listado(self):
        cambios = {"nombre":"Sucursal corregida", "tipo_ubicacion_id":str(self.otro_tipo.pk), "pais_id":str(self.pais.pk),
            "departamento":"Francisco Morazán", "municipio":"Distrito Central", "ciudad":"Tegucigalpa", "colonia":"Kennedy",
            "direccion":"Dirección corregida", "latitud":"14.072300", "longitud":"-87.192100", "telefono":"9999-9999",
            "nombre_contacto":"María", "horario_atencion":{"lunes":"08:00-17:00"}, "instrucciones":"Portón norte"}
        respuesta = self._patch(cambios)
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        self.ubicacion.refresh_from_db()
        self.assertEqual(self.ubicacion.tipo_ubicacion_id, self.otro_tipo.pk)
        self.assertEqual(self.ubicacion.nivel_administrativo_1, "Francisco Morazán")
        self.assertEqual(self.ubicacion.latitud, Decimal("14.072300"))
        ubicacion = respuesta.json()["ubicacion"]
        for campo in cambios.keys() - {"tipo_ubicacion_id", "pais_id"}:
            self.assertEqual(ubicacion[campo], cambios[campo], campo)
        listado = self.cliente.get(reverse("ubicaciones:lista-creacion-ubicaciones"), {"empresa_id":self.empresa.pk})
        self.assertEqual(listado.status_code, 200)
        self.assertEqual(respuesta.json(), listado.json()["resultados"][0])
        detalle = self.cliente.get(self.url)
        self.assertEqual(detalle.json(), ubicacion)
        self.assertNotIn("nivel_administrativo_1", ubicacion)
        self.assertNotIn("nivel_administrativo_2", ubicacion)
        self.assertNotIn("localidad", ubicacion)

    def test_parcial_preserva_campos_omitidos_y_autorizacion(self):
        creado, actualizado = self.ubicacion.creado_en, self.ubicacion.actualizado_en
        respuesta = self._patch({"telefono":"8888-8888"})
        self.assertEqual(respuesta.status_code, 200)
        self.ubicacion.refresh_from_db(); self.relacion.refresh_from_db()
        self.assertEqual(self.ubicacion.nombre, "Sucursal original")
        self.assertEqual(self.ubicacion.creado_en, creado)
        self.assertGreater(self.ubicacion.actualizado_en, actualizado)
        self.assertTrue(self.ubicacion.verificada)
        self.assertEqual(self.ubicacion.creada_por, self.superadministrador.pk)
        self.assertEqual((self.relacion.permite_origen, self.relacion.permite_destino, self.relacion.estado), (True,False,"PENDIENTE"))
        self.assertEqual(respuesta.data["estado"], "PENDIENTE")

    def test_se_pueden_limpiar_campos_opcionales(self):
        campos = {c:None for c in ("departamento","municipio","ciudad","colonia","telefono","nombre_contacto","horario_atencion","instrucciones")}
        r = self._patch(campos)
        self.assertEqual(r.status_code, 200, r.data)
        for campo in campos:
            self.assertIsNone(r.data["ubicacion"][campo], campo)

    def test_patch_solo_latitud_conserva_longitud(self):
        r = self._patch({"latitud":"14.100000"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["ubicacion"]["longitud"], "-88.030000")

    def test_requiere_empresa_y_al_menos_un_cambio(self):
        for datos, campo in (({"nombre":"Nuevo"},"empresa_id"), ({"empresa_id":"invalido", "nombre":"Nuevo"},"empresa_id"),
                             ({"empresa_id":str(self.empresa.pk)},"detail"), ({},"empresa_id")):
            r = self.cliente.patch(self.url, datos, format="json")
            self.assertEqual(r.status_code, 400)
            self.assertIn(campo, r.data)

    def test_rechaza_campos_no_editables_sin_cambiar_la_ubicacion(self):
        for campo in ("id", "estado", "permite_origen", "permite_destino", "origen", "identificador_lugar_google",
                      "verificada", "creada_por", "creado_en", "actualizado_en", "nivel_administrativo_1", "ubicacion"):
            r = self._patch({"nombre":"No guardar", campo:"valor"})
            self.assertEqual(r.status_code, 400, campo)
            self.assertIn(campo, r.data)
        self.ubicacion.refresh_from_db()
        self.assertEqual(self.ubicacion.nombre, "Sucursal original")

    def test_validaciones_de_valores_conservan_nombres_publicos(self):
        casos = (("nombre",""), ("nombre","x"*201), ("direccion",None), ("direccion",""),
            ("latitud","90.000001"), ("latitud","NaN"), ("longitud","-180.000001"),
            ("latitud","14.1234567"), ("telefono","x"*33), ("tipo_ubicacion_id",None),
            ("tipo_ubicacion_id","invalido"), ("pais_id",None), ("departamento","x"*151))
        for campo, valor in casos:
            r = self._patch({campo:valor})
            self.assertEqual(r.status_code, 400, (campo,valor))
            self.assertIn(campo, r.data)

    def test_catalogos_inexistentes_o_inactivos_se_rechazan_sin_escritura_parcial(self):
        for campo in ("tipo_ubicacion_id", "pais_id"):
            r = self._patch({"nombre":"No guardar", campo:str(uuid4())})
            self.assertEqual(r.status_code, 400)
            self.assertIn(campo, r.data)
        self.otro_tipo.activo = False
        self.otro_tipo.save(update_fields=("activo",))
        r = self._patch({"nombre":"No guardar", "tipo_ubicacion_id":str(self.otro_tipo.pk)})
        self.assertEqual(r.status_code, 400)
        self.assertIn("tipo_ubicacion_id", r.data)
        self.pais.activo = False
        self.pais.save(update_fields=("activo",))
        r = self._patch({"nombre":"No guardar", "pais_id":str(self.pais.pk)})
        self.assertEqual(r.status_code, 400)
        self.assertIn("pais_id", r.data)
        self.ubicacion.refresh_from_db()
        self.assertEqual(self.ubicacion.nombre, "Sucursal original")

    def test_sin_sesion_responde_401(self):
        self.cliente.force_authenticate(None)
        self.assertEqual(self._patch({"nombre":"Nuevo"}).status_code, 401)

    def test_lectura_o_creacion_no_otorgan_edicion(self):
        for codigo in ("ubicacion.ver", "ubicacion.crear"):
            self.cliente.force_authenticate(self._usuario_con_permiso(codigo))
            self.assertEqual(self._patch({"nombre":"Nuevo"}).status_code, 403)

    def test_alcance_de_sucursal_no_permite_editar_catalogo_de_empresa(self):
        sucursal = Sucursal.objects.create(empresa=self.empresa, ubicacion=self.ubicacion, nombre="Sucursal")
        self.cliente.force_authenticate(self._usuario_con_permiso("ubicacion.aprobar", sucursal=sucursal))
        self.assertEqual(self._patch({"nombre":"Nuevo"}).status_code, 404)

    def test_empresas_y_ubicaciones_ajenas_o_inexistentes_no_se_revelan(self):
        self.assertEqual(self._patch({"nombre":"Nuevo"}, ubicacion=self.ajena).status_code, 404)
        self.assertEqual(self._patch({"nombre":"Nuevo"}, ubicacion=self.ajena, empresa=self.otra_empresa).status_code, 404)
        r = self.cliente.patch(reverse("ubicaciones:detalle-ubicacion", args=[uuid4()]),
            {"empresa_id":str(self.empresa.pk), "nombre":"Nuevo"}, format="json")
        self.assertEqual(r.status_code, 404)

    def test_corporate_ni_siquiera_con_permiso_global_edita_otra_empresa(self):
        self.cliente.force_authenticate(self.superadministrador)
        r = self._patch({"nombre":"No guardar"}, ubicacion=self.ajena, empresa=self.otra_empresa)
        self.assertEqual(r.status_code, 404)
        self.ajena.refresh_from_db()
        self.assertEqual(self.ajena.nombre, "Ajena")

    def test_empresa_inactiva_no_se_edita(self):
        self.empresa.estado = "INACTIVO"
        self.empresa.save(update_fields=("estado",))
        self.assertEqual(self._patch({"nombre":"Nuevo"}).status_code, 404)

    def test_corporate_no_modifica_ubicacion_compartida_ni_con_permiso_global(self):
        UbicacionEmpresa.objects.create(empresa=self.otra_empresa, ubicacion=self.ubicacion, estado="INACTIVO")
        for usuario in (self.administrador,self.superadministrador):
            self.cliente.force_authenticate(usuario)
            r = self._patch({"nombre":"No guardar"})
            self.assertEqual(r.status_code, 403)
            self.assertIn("compartida", str(r.data))

    def test_sucursal_de_otra_empresa_tambien_impide_editar_datos_compartidos(self):
        Sucursal.objects.create(empresa=self.otra_empresa, ubicacion=self.ubicacion, nombre="Sucursal ajena")
        self.assertEqual(self._patch({"nombre":"No guardar"}).status_code, 403)

    @override_settings(MODO_APLICACION="EXTERNO")
    def test_network_empresa_edita_solo_ubicaciones_propias_no_compartidas(self):
        asignacion = RolUsuario.objetos.get(usuario=self.administrador)
        asignacion.rol = Rol.objetos.get(codigo="ADMINISTRADOR_EMPRESA_EXTERNA")
        asignacion.save(update_fields=("rol",))
        self.assertEqual(self._patch({"nombre":"Network"}).status_code, 200)
        self.assertEqual(self._patch({"nombre":"Ajena"}, ubicacion=self.ajena, empresa=self.otra_empresa).status_code, 404)
        UbicacionEmpresa.objects.create(empresa=self.otra_empresa, ubicacion=self.ubicacion)
        self.assertEqual(self._patch({"nombre":"Compartida"}).status_code, 403)

    @override_settings(MODO_APLICACION="EXTERNO")
    def test_network_global_puede_editar_catalogo_compartido_sin_modificar_autorizaciones(self):
        otra_relacion = UbicacionEmpresa.objects.create(empresa=self.otra_empresa, ubicacion=self.ubicacion,
            permite_origen=False, permite_destino=True, estado="RECHAZADO")
        self.cliente.force_authenticate(self.superadministrador)
        r = self._patch({"nombre":"Nombre corregido"})
        self.assertEqual(r.status_code, 200, r.data)
        otra_relacion.refresh_from_db()
        self.assertEqual((otra_relacion.permite_origen,otra_relacion.permite_destino,otra_relacion.estado), (False,True,"RECHAZADO"))
        self.assertEqual(r.data["empresa_id"], str(self.empresa.pk))
        self.assertEqual(r.data["ubicacion"]["nombre"], "Nombre corregido")

    def test_revocar_permiso_bloquea_el_siguiente_patch(self):
        self.assertEqual(self._patch({"nombre":"Primera edición"}).status_code, 200)
        RolUsuario.objetos.filter(usuario=self.administrador).update(
            activo=False, revocado_por=self.superadministrador, revocado_en=timezone.now())
        self.assertEqual(self._patch({"nombre":"No guardar"}).status_code, 403)
        self.ubicacion.refresh_from_db()
        self.assertEqual(self.ubicacion.nombre, "Primera edición")
