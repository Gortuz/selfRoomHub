# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
Una persona en su propio cuarto. El panel vive en un Android viejo acostado sobre el escritorio, a unos 60 cm, junto a la computadora: se mira de reojo mientras se trabaja o estudia y se toca seguido. Cualquiera que replique el proyecto lo usa en una situación parecida, con su propio equipo.

## Product Purpose
selfRoomHub es domótica casera sin hub comercial: un Android viejo corre el backend y controla dispositivos Wi-Fi y el audio Bluetooth del cuarto por red local. El panel es su cara visible: dice qué está sonando, deja controlar la reproducción, el volumen y los parlantes, y avisa cuando algo del sistema no funciona. Éxito: una mirada basta para saber qué suena, y un toque para cambiarlo.

## Positioning
El servidor es a la vez el reproductor: la música (Spotify Connect) sale del mismo teléfono que muestra el panel y que controla el enchufe de los parlantes. El panel refleja el estado real del cuarto, no una app de streaming genérica.

## Operating Context
- Escritorio, horizontal siempre, ~60 cm de distancia, uso de día y de noche.
- La música es lo primero que se quiere saber; la hora va después; el control del cuarto (parlantes hoy, focos después) es secundario.
- El mismo panel se abre en navegadores de otros equipos de la casa (Mac, iPhone, iPod) como control remoto.
- Datos disponibles en vivo: canción, artista, álbum, portada (hasta 640 px), reproduciendo/en pausa, volumen de medios (16 pasos en Android), estado del enchufe, si el audio Bluetooth está en el servidor, salud del control Bluetooth (Shizuku).

## Capabilities and Constraints
- Web estática servida por el backend (`/panel/`), sin build ni dependencias; ES2015 para navegadores viejos.
- En el servidor la muestra una app kiosco (WebView a pantalla completa, pantalla siempre encendida).
- De noche no debe iluminar el cuarto: brillo mínimo o casi negro.
- Requiere token del backend; se pega una vez por navegador.
- Sin clima por ahora (no se pidió); focos y escenas llegarán después.

## Product Principles
1. La música manda: lo que suena ocupa el lugar principal.
2. Nada irreversible con un toque: apagar algo pide confirmación con información.
3. Un vistazo de reojo basta: jerarquía legible a 60 cm.
4. El cuarto de noche es oscuro: el panel no debe iluminarlo.
5. Replicable: nada específico de una instalación en la interfaz.
