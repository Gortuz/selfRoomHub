---
name: selfRoomHub
description: Panel del cuarto como afiche chicha; lo que suena se imprime en tintas fluorescentes sobre negro.
colors:
  ink-1: "#ffe600"
  ink-2: "#ff3ea5"
  ink-3: "#39ff7a"
  ground: "#0c0b0e"
  ground-raised: "#1a1720"
  bone: "#f2ede3"
  bone-soft: "#b8b1a6"
  rule: "#3a3541"
  led-off: "#4a4452"
  alert: "#ff7a5c"
typography:
  display:
    fontFamily: "Bungee, Arial Black, sans-serif"
    fontSize: "84px"
    fontWeight: 400
    lineHeight: 0.95
  headline:
    fontFamily: "Bungee, Arial Black, sans-serif"
    fontSize: "clamp(28px, 11vh, 56px)"
    fontWeight: 400
    lineHeight: 1
    fontFeature: "tnum"
  title:
    fontFamily: "Bungee, Arial Black, sans-serif"
    fontSize: "26px"
    fontWeight: 400
  body-strong:
    fontFamily: "Atkinson Hyperlegible, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "clamp(16px, 5vh, 24px)"
    fontWeight: 700
  body:
    fontFamily: "Atkinson Hyperlegible, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "17px"
    fontWeight: 400
    lineHeight: 1.45
  label:
    fontFamily: "Atkinson Hyperlegible, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "14px"
    fontWeight: 400
rounded:
  none: "0"
  round: "50%"
  pill: "999px"
spacing:
  pad: "clamp(14px, 3.6vmin, 36px)"
  tight: "10px"
  gap: "12px"
  wide: "14px"
components:
  key:
    backgroundColor: "transparent"
    textColor: "{colors.bone}"
    rounded: "{rounded.round}"
    size: "52px"
  key-active:
    backgroundColor: "{colors.ground-raised}"
  key-main:
    backgroundColor: "{colors.ink-1}"
    textColor: "{colors.ground}"
    rounded: "{rounded.round}"
    size: "64px"
  key-main-active:
    backgroundColor: "{colors.bone}"
  speakers:
    backgroundColor: "transparent"
    textColor: "{colors.bone}"
    rounded: "{rounded.pill}"
    padding: "0 16px 0 14px"
    height: "44px"
  action:
    backgroundColor: "transparent"
    textColor: "{colors.bone}"
    rounded: "{rounded.none}"
    padding: "0 18px"
    height: "50px"
  action-primary:
    backgroundColor: "{colors.bone}"
    textColor: "{colors.ground}"
    rounded: "{rounded.none}"
    padding: "0 18px"
    height: "50px"
  action-quiet:
    backgroundColor: "transparent"
    textColor: "{colors.bone-soft}"
    rounded: "{rounded.none}"
  sheet:
    backgroundColor: "{colors.ground-raised}"
    textColor: "{colors.bone}"
    rounded: "{rounded.none}"
    padding: "20px 24px 22px"
    width: "540px"
  input-token:
    backgroundColor: "{colors.ground-raised}"
    textColor: "{colors.bone}"
    rounded: "{rounded.none}"
    padding: "0 14px"
    height: "48px"
---

# Design System: selfRoomHub

## Overview

**Creative North Star: "El afiche chicha del día"**

El panel es un cartel de imprenta andino pegado sobre negro. Lo que suena se imprime como titular enorme, en mayúsculas de letrero y en bandas horizontales de tinta fluorescente plana; todo lo demás es blanco hueso sobre negro, quieto y legible a 60 cm. Las tintas no son fijas: cada portada nueva las recalcula, así que el afiche cambia de color con cada canción sin cambiar de forma.

La densidad es baja y la jerarquía es de cartel: portada cuadrada, titular, artista, consola. El color es una zona, no un recubrimiento. No hay vidrio, ni desenfoque de portada, ni degradados suaves; cuando aparece un degradado en CSS es un corte duro que imita tinta plana. De noche el panel entero baja a un tercio para no iluminar el cuarto.

Se rechaza explícitamente la pantalla "Reproduciendo" de las apps de streaming: portada con fondo borroso y controles grises.

**Key Characteristics:**
- Negro de imprenta con blanco hueso; color solo en tinta plana.
- Tres tintas fluorescentes que se recalculan desde la portada.
- Titular Bungee en mayúsculas, ajustado al espacio libre, pintado en bandas de corte duro.
- Controles como consola impresa: teclas cuadradas con filete, fader vertical con perilla, LED redondo.
- Superficies impresas: esquinas rectas en hojas, campos y acciones.

## Colors

Negro de imprenta, blanco hueso y tres tintas fluorescentes que cambian con cada portada.

### Primary
- **Tinta 1, Amarillo Letrero** (ink-1): la tinta principal. Primera banda del titular, la hora, el LED encendido, la tecla de reproducir, el filo superior de la hoja, el anillo de foco y el cursor de texto. Es la que se recalcula primero desde el tono más presente de la portada.

### Secondary
- **Tinta 2, Rosa Chicha** (ink-2): segunda banda del titular, relleno del fader y fondo de la selección de texto.

### Tertiary
- **Tinta 3, Verde Neón** (ink-3): tercera banda del titular y texto en código dentro del formulario del token.

### Neutral
- **Negro de Imprenta** (ground): fondo de todo el panel y texto sobre tinta o sobre hueso.
- **Negro Plancha** (ground-raised): fondo de la hoja, de los campos, de la portada sin imagen y estado presionado de teclas.
- **Blanco Hueso** (bone): texto principal, artista, iconos de teclas, perilla del fader, acción primaria.
- **Hueso Gastado** (bone-soft): fecha, etiquetas, términos de la hoja, acciones discretas, ayuda.
- **Filete** (rule): bordes de 2px de teclas y acciones, separadores de 1px, pista vacía del fader.
- **LED Apagado** (led-off): punto del LED cuando el equipo está apagado.
- **Aviso Coral** (alert): mensajes de error y de estado del sistema. Solo texto, nunca relleno.

### Named Rules
**La Regla de las Tintas Vivas.** Las tintas se derivan de la portada en tiempo real: los tres tonos más presentes (saturación mínima 0.25, luz entre 0.12 y 0.92) se llevan a `hsl(h, 100%, 58%)`, y a 68% de luz entre 200° y 290° para que los azules se lean sobre negro. Si no hay portada o no hay tonos suficientes, vuelven los valores de reposo. Ningún componente usa un color de tinta fijo; siempre `var(--ink-n)`.

**La Regla de Tinta Plana.** Todo color es plano. Un degradado solo existe con cortes duros (`0 34%, 34% 67%`) para imitar bandas o rellenos impresos; nunca transiciones suaves, nunca vidrio ni desenfoque.

**La Regla de Una Zona de Color.** El titular es la única zona con varias tintas. Fuera de él, la tinta aparece en puntos pequeños y funcionales (hora, LED, tecla principal, filo de la hoja, foco) y el resto es hueso sobre negro.

## Typography

**Display Font:** Bungee (con Arial Black)
**Body Font:** Atkinson Hyperlegible (con system-ui, -apple-system, Segoe UI)

**Character:** Letra de cartel pintado contra una sans hecha para leerse de lejos. Bungee grita lo que suena; Atkinson informa todo lo demás sin competir.

### Hierarchy
- **Display** (Bungee 400, ajustado por script entre 18px y 84px, hasta 220px en reposo; parte solo entre palabras; interlineado 0.95, 0.9 en reposo; mayúsculas): el titular de la canción o la hora en reposo. Ocupa todo el espacio libre del afiche y corta en cualquier punto (`overflow-wrap: anywhere`).
- **Headline** (Bungee 400, clamp(28px, 11vh, 56px), interlineado 1, cifras tabulares): la hora en la barra superior.
- **Title** (Bungee 400, 26px; 22px en el formulario del token): títulos de la hoja y del formulario, en tinta 1.
- **Body Strong** (Atkinson 700, clamp(16px, 5vh, 24px)): el artista, una línea con elipsis. Los botones usan Atkinson 700 a 16px.
- **Body** (Atkinson 400, 15 a 17px, interlineado 1.45 en ayuda): filas de la hoja (17px), campos (17px), avisos (15px).
- **Label** (Atkinson 400, 14px; la fecha usa clamp(14px, 3.8vh, 18px)): etiqueta del fader, fecha. El valor del volumen va en 700 y cifras tabulares.

### Named Rules
**La Regla del Titular que Llena.** El tamaño del titular no se fija en CSS: se busca el mayor que entra en el alto y ancho libres del afiche, bajando de 3 en 3 px, y se vuelve a medir al cambiar tamaño y cuando la fuente termina de cargar.

**La Regla de Dos Voces.** Bungee solo para titular, hora y títulos de hoja o formulario. Toda la interfaz restante es Atkinson Hyperlegible, en 400 o 700, sin otros pesos.

## Layout

Una sola pantalla horizontal, sin desplazamiento (`overflow: hidden`). Rejilla de tres columnas: portada cuadrada a toda la altura (alto de la ventana menos dos márgenes), escenario flexible y canal de volumen vertical de 64px a toda la altura. El escenario es una columna: barra superior (hora y fecha), afiche que toma todo el alto sobrante con base 0, y consola abajo (teclas de transporte y botón Parlantes). Bajo el titular, una línea de versión en hueso gastado ("Remastered 2009", "feat. …") separada del nombre. Los avisos van debajo de la consola.

El margen general es `pad`, que escala con la ventana entre 14 y 36px y respeta las zonas seguras laterales. Los espacios internos son pocos y cortos: 10px entre teclas y bajo el titular, 12px antes del fader, 14px entre hora y fecha.

En reposo (sin canción) la portada desaparece, la rejilla pasa a una columna y la hora sale de la barra para ocupar el lugar del titular, como afiche. En vertical (navegadores de otros equipos) la portada sube arriba, a lo ancho y con tope de 46vh.

**La Regla de la Noche.** Entre las 23:00 y las 6:00 todo el panel, la hoja de parlantes y el formulario del token bajan a opacidad 0.34 y la tecla de reproducir pierde su relleno de tinta (queda en contorno). Nada nuevo debe sumar luz de noche.

## Elevation & Depth

Plano por defecto. La profundidad se marca por tono (negro de imprenta contra negro plancha) y por filetes de 2px, no por sombras. La portada no lleva sombra ni brillo. La única capa elevada es la hoja inferior, que sube sobre un velo del color del fondo al 72%.

### Shadow Vocabulary
- **Sombra de hoja** (`box-shadow: 0 -16px 40px rgba(0, 0, 0, 0.5)`): solo bajo la hoja inferior, hacia arriba, para separarla del panel velado.

### Named Rules
**La Regla de la Plancha.** Las superficies son papel impreso: sin sombra en reposo, sin vidrio, sin desenfoque. Solo una capa modal puede proyectar sombra.

## Shapes

Una sola familia de forma: todo es plancha impresa de esquinas rectas. Teclas de transporte (56px), pasos de volumen (56px), botón Parlantes, acciones de la hoja, campo del token y perilla del fader son rectángulos con filete de 2px; la tecla de reproducir va rellena de tinta 1. La única forma redonda es el LED (12px), porque es una luz, no un control.

**La Regla Consola o Imprenta.** Si se presiona como un aparato (tecla, interruptor, indicador), es redondo. Si se lee o se llena como papel (hoja, campo, acción de texto), es recto.

## Components

### Teclas de transporte
Botones de consola, redondos y táctiles.
- **Forma:** círculo de 52px con filete de 2px; icono SVG relleno de 22px en hueso.
- **Principal (reproducir/pausa):** 64px, relleno y borde de tinta 1, icono de 26px en negro. Alterna iconos de reproducir y pausa según el estado.
- **Presionado:** las teclas normales se rellenan de negro plancha; la principal pasa a hueso.
- **Foco:** contorno de 3px en tinta 1 separado 3px.
- **Noche:** la principal queda transparente con icono en tinta 1.

### Canal de volumen (fader vertical)
Fader de canal de mesa de mezcla, al borde derecho y a toda la altura.
- **Pasos:** botones redondos + arriba y − abajo (52px, filete de 2px); cada toque es un paso real de Android (16 pasos, ~7 %).
- **Riel:** 6px de ancho, filete vacío y relleno de tinta 2 desde abajo hasta el valor.
- **Perilla:** rectángulo de 40 por 22px en hueso con ranura negra al centro (corte duro 42%-58%), esquinas rectas; en tinta 2 mientras se arrastra.
- **Valor:** debajo, hueso 700 a 15px con cifras tabulares y " %". El valor se envía al soltar; el panel ignora 3 s el valor del servidor tras un cambio local para que la perilla no salte.
- Solo aparece cuando el servidor informa el volumen; igual que las teclas.

### Botón Parlantes con LED
- **Forma:** rectángulo de 56px de alto con filete de 2px y esquinas rectas, texto Atkinson 700 a 16px.
- **Lugar:** en la consola, después de las teclas de transporte y separado de ellas; siempre visible aunque falten las teclas.
- **LED:** círculo de 12px a la izquierda; LED apagado cuando no hay corriente, tinta 1 cuando está encendido. Parpadea en dos pasos (0.8s, `steps(2)`) mientras una orden está en curso.
- **Presionado:** fondo negro plancha.

### Hoja inferior (menú de parlantes)
Una hoja de cartel que sube desde abajo; nada se apaga sin ver antes la información.
- **Fondo:** negro plancha, hasta 540px de ancho, filo superior de tinta 1 de 6px, esquinas rectas.
- **Entrada:** sube 28px en 0.24s con `cubic-bezier(0.16, 1, 0.3, 1)`; sin animación con movimiento reducido.
- **Contenido:** título Bungee en tinta 1; filas término/valor separadas por filete de 1px, término en hueso gastado y valor con LED a la derecha; mensaje de error en coral.
- **Cierre:** tocar el velo, Escape o la acción "Cerrar".

### Acciones
- **Forma:** rectángulos rectos de 50px de alto mínimo, filete de 2px, Atkinson 700 a 16px.
- **Primaria:** relleno y borde hueso, texto negro.
- **Discreta:** sin relleno, texto hueso gastado en 400.
- **Deshabilitada / ocupada:** opacidad 0.45 / 0.7.

### Campo de texto (token)
- **Estilo:** 48px de alto, fondo negro plancha, filete de 2px, esquinas rectas, Atkinson 17px, cursor en tinta 1.
- **Foco:** el mismo contorno de 3px en tinta 1.
- **Error:** texto coral debajo, nunca borde rojo.

### Titular en bandas (firma)
El titular, o la hora en reposo, en Bungee mayúscula con un relleno de texto de tres bandas horizontales de corte duro (tinta 1 hasta 34%, tinta 2 hasta 67%, tinta 3 hasta el final). La franja mide exactamente el interlineado (0.95em; 0.9em en reposo) y se repite por línea, así que cada renglón lleva las tres tintas como un cartel chicha. Es la única excepción sancionada de texto con degradado: solo existe con cortes duros, solo con las tintas de la portada, y solo en el titular. Una canción en pausa añade "· en pausa" en hueso gastado tras el artista, sin cambiar el titular.

## Do's and Don'ts

### Do:
- **Do** tomar todo color de acento de `var(--ink-1)`, `var(--ink-2)` o `var(--ink-3)`, porque cambian con cada portada.
- **Do** mantener el texto de la interfaz en blanco hueso (#f2ede3) o hueso gastado (#b8b1a6) sobre negro (#0c0b0e).
- **Do** usar Bungee solo para el titular, la hora y títulos de hoja; Atkinson Hyperlegible 400/700 para el resto.
- **Do** dibujar bandas y rellenos con cortes duros de degradado, como tinta plana.
- **Do** hacer redondos los controles de consola y rectos los elementos impresos.
- **Do** usar el mismo foco en todo control: contorno de 3px en tinta 1 separado 3px.
- **Do** dejar que la noche (23:00 a 6:00) baje todo a opacidad 0.34; cualquier superficie nueva debe atenuarse igual.

### Don't:
- **Don't** usar portada desenfocada de fondo, vidrio, transparencias decorativas ni controles grises de streaming.
- **Don't** usar degradados suaves; el único texto con degradado es el titular en bandas de corte duro.
- **Don't** fijar colores de tinta en hex dentro de un componente.
- **Don't** repartir varias tintas fuera del titular; fuera de él, una tinta por elemento y en puntos pequeños.
- **Don't** poner sombras en superficies en reposo; solo la hoja modal proyecta sombra.
- **Don't** usar el coral de aviso como relleno ni como borde; es solo texto.
