"""Arranque del temporizador por worker, incluso al usar precarga de WSGI."""


def post_worker_init(worker):
    from apps.evidencias.planificador import iniciar_planificador_imagenes
    iniciar_planificador_imagenes()
