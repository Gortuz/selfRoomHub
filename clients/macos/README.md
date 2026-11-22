# Agente de la Mac (opcional)

Para parlantes Bluetooth emparejados con una Mac y un iPhone. Muchos parlantes se reconectan al último dispositivo al encenderse, y una Mac dormida sigue aceptando conexiones Bluetooth: el parlante termina en la Mac aunque lo enciendas desde el iPhone.

Este agente usa `sleepwatcher` y `blueutil`:

- **Al dormir**: desconecta el parlante y apaga el Bluetooth de la Mac.
- **Al encender la pantalla**: prende el Bluetooth. No reconecta el parlante; eso lo hace el atajo de la Mac.

Consecuencia: con la Mac dormida no se puede despertar con teclado o mouse Bluetooth (sí con el trackpad, teclado interno o abriendo la tapa).

## Instalar

```bash
blueutil --paired                                   # busca la dirección del parlante
zsh clients/macos/install.sh aa-bb-cc-dd-ee-ff
```

## Atajo "Speakers on" con detección de dispositivo

En la Mac, después de encender el enchufe, el atajo ejecuta `blueutil --connect <dirección>` (acción *Ejecutar script de shell*; requiere activar "Permitir ejecutar scripts" en los ajustes de Atajos). iOS no puede iniciar una conexión Bluetooth de forma confiable desde Atajos: en el iPhone, si el parlante no se conecta solo, hay que tocarlo en Ajustes → Bluetooth.

## Desinstalar

```bash
launchctl bootout gui/$(id -u)/dev.selfroomhub.sleepwatcher
rm ~/Library/LaunchAgents/dev.selfroomhub.sleepwatcher.plist ~/.config/selfroomhub/macos.env
```

Con eso el Bluetooth de la Mac vuelve a su comportamiento normal (sigue prendido al dormir).

- `blueutil` y `sleepwatcher` quedan instalados, pero no hacen nada por sí solos. Para quitarlos: `brew uninstall sleepwatcher blueutil`.
- Si desinstalas `blueutil`, el atajo "Speakers on" de la Mac seguirá encendiendo el enchufe, pero el paso que conecta el Bluetooth fallará. Quita también esa acción del atajo.
- Si el Bluetooth de la Mac queda apagado (por ejemplo, si quitaste el agente con la pantalla apagada), préndelo desde el Centro de control o con `blueutil --power 1`.
