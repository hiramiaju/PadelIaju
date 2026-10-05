# IAJU · Reservación de canchas de pádel — Python Flask

Versión en **Python + Flask** con los logos oficiales del Instituto de la Juventud, reservaciones públicas, horarios fijos semanales, pase de acceso descargable, panel de administración y persistencia en JSON.

## Cambios de esta versión

- Bloques públicos de **1 hora**.
- El usuario puede reservar **1 o 2 horas consecutivas**.
- Si una persona completa **2 horas en un mismo día**, no puede volver a reservar durante los **4 días siguientes**.
- Se eliminó la regla anterior que impedía repetir el mismo horario varias semanas: ahora **sí se puede reservar en semanas consecutivas**.
- Navegación rápida por fecha, botón **+1 semana** y reservaciones hasta **90 días** hacia adelante.
- **Sábados:** servicio de 08:00 a 19:00.
- **Domingos:** cerrado.
- Lunes a viernes se manejan bloques de 08:00 a 23:00.
- Después de reservar se genera un **pase de acceso PNG descargable**, pensado para presentarlo al ingresar.
- El mismo pase puede enviarse por correo (si SMTP está configurado) y se prepara un mensaje para WhatsApp.
- El panel admin permite ver, agregar y eliminar **reservaciones fijas semanales**.

## Reservaciones fijas semanales precargadas

| Día | Persona | Cancha | Horario |
|---|---|---|---|
| Lunes | Silvia Garfias | Cancha 2 | 20:00–23:00 |
| Martes | Sergio Castañeda | Cancha 1 | 19:00–21:00 |
| Martes | Gilberto Navarro | Cancha 2 | 18:00–20:00 |
| Miércoles | Mario Sosa | Cancha 1 | 18:00–20:00 |
| Miércoles | Mario Sosa | Cancha 2 | 18:00–20:00 |
| Jueves | Paola Díaz | Cancha 1 | 19:00–21:00 |
| Jueves | Karina Galaviz | Cancha 2 | 18:00–20:00 |
| Viernes | Luis Rendón | Cancha 2 | 18:00–20:00 |
| Lunes | Jonathan Olivas | Cancha 2 | 08:00–11:00 |
| Miércoles | Jonathan Olivas | Cancha 2 | 08:00–11:00 |
| Viernes | Jonathan Olivas | Cancha 2 | 08:00–11:00 |

Las reservaciones fijas están en `data/reservas_fijas.json`. El sistema las aplica automáticamente cada semana sin tener que generar cientos de registros repetidos.

## Estructura

```text
Padeliaju-Flask/
├─ app.py
├─ requirements.txt
├─ .env.example
├─ Procfile
├─ render.yaml
├─ run.bat
├─ run.sh
├─ data/
│  ├─ reservas.json
│  ├─ reservas_fijas.json
│  └─ bloqueos.json
├─ templates/
│  ├─ index.html
│  └─ admin.html
└─ static/
   ├─ app.js
   ├─ styles.css
   └─ images/
      ├─ iaju-azul.png
      ├─ iaju-blanco.png
      └─ iaju-color.png
```

## Ejecutarlo en Windows

La forma más sencilla es hacer doble clic en `run.bat`. La primera vez crea un entorno virtual, instala dependencias, crea `.env` a partir de `.env.example` y levanta Flask.

Manual:

```powershell
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python app.py
```

Después abre:

- Página pública: `http://127.0.0.1:5000`
- Administración: `http://127.0.0.1:5000/admin`

Cambia `ADMIN_PASSWORD` antes de publicar el sistema.

## Configuración `.env`

```env
ADMIN_PASSWORD=cambia-esta-clave
INSTITUTE_WHATSAPP=5215500000000
DATA_DIR=./data
LOCAL_TIMEZONE=America/Mexico_City

SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=tu-correo@ejemplo.com
SMTP_PASS=tu-contrasena-de-aplicacion
FROM_EMAIL=tu-correo@ejemplo.com
ADMIN_EMAIL=

PORT=5000
FLASK_DEBUG=1
```

Si SMTP no está configurado, la reservación **sí se guarda** y el usuario **sí puede descargar su pase PNG**; únicamente se omite el envío automático por correo.

## Persistencia en Render

El proyecto incluye `render.yaml` y `Procfile`. El Blueprint monta un disco persistente en `/var/data`, por lo que las reservaciones y cambios del panel admin no se pierden al desplegar de nuevo.

Comando de producción:

```bash
gunicorn --workers 1 --threads 4 --timeout 60 app:app
```

Se usa un solo worker porque la persistencia es mediante JSON y el bloqueo de escritura es por proceso.

## API principal

- `GET /api/config`
- `GET /api/availability?date=YYYY-MM-DD`
- `POST /api/reservations`
- `POST /api/reservations/<id>/email-ticket`
- `POST /api/reservations/cancel`
- `POST /api/admin/login`
- `GET /api/admin/reservations`
- `GET /api/admin/stats`
- `DELETE /api/admin/reservations/<id>`
- `GET /api/admin/fixed-reservations`
- `POST /api/admin/fixed-reservations`
- `DELETE /api/admin/fixed-reservations/<id>`
- `GET /api/admin/blocks`
- `POST /api/admin/blocks`
- `DELETE /api/admin/blocks/<id>`
