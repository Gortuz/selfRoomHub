"""Genera atajos de Apple (.shortcut) para selfRoomHub y los firma para importarlos.

Uso (en una Mac):
    SELFROOMHUB_TOKEN=... python3 clients/shortcuts/generate.py \
        --url http://192.168.1.20:8000 --device parlantes \
        --bt-id parlantes --bt-address AA:BB:CC:DD:EE:FF --out /tmp/atajos

Crea "Speakers on", "Speakers off", "Speakers", "Movie mode" y "Music mode".
El token queda dentro de cada atajo: no compartas los archivos generados.
"""

from __future__ import annotations

import argparse
import os
import plistlib
import subprocess
import sys
import uuid
from pathlib import Path

BLUEUTIL = "/opt/homebrew/bin/blueutil"


def _uuid() -> str:
    return str(uuid.uuid4()).upper()


def _text(s: str) -> dict:
    return {"Value": {"string": s}, "WFSerializationType": "WFTextTokenString"}


def _dict(items: list[dict]) -> dict:
    return {
        "Value": {"WFDictionaryFieldValueItems": items},
        "WFSerializationType": "WFDictionaryFieldValue",
    }


def _act(ident: str, **params) -> dict:
    return {"WFWorkflowActionIdentifier": f"is.workflow.actions.{ident}", "WFWorkflowActionParameters": params}


def request(url: str, token: str, body_on: bool | None = None) -> dict:
    params = {
        "UUID": _uuid(),
        "WFURL": url,
        "WFHTTPMethod": "POST",
        "ShowHeaders": True,
        "WFHTTPHeaders": _dict(
            [{"WFItemType": 0, "WFKey": _text("Authorization"), "WFValue": _text(f"Bearer {token}")}]
        ),
    }
    if body_on is not None:
        params["WFHTTPBodyType"] = "JSON"
        params["WFJSONValues"] = _dict(
            [
                {
                    "WFItemType": 4,
                    "WFKey": _text("on"),
                    "WFValue": {"Value": body_on, "WFSerializationType": "WFNumberSubstitutableState"},
                }
            ]
        )
    return _act("downloadurl", **params)


def shell(script: str) -> dict:
    return _act("runshellscript", UUID=_uuid(), Shell="/bin/zsh", InputMode="to stdin", Script=script)


def comment(text: str) -> dict:
    return _act("comment", WFCommentActionText=text)


def if_mac(then: list[dict], otherwise: list[dict]) -> list[dict]:
    """Bloque Si/Si no según el modelo del dispositivo que ejecuta el atajo."""
    details, group = _uuid(), _uuid()
    model = {
        "Type": "Variable",
        "Variable": {
            "Value": {"OutputUUID": details, "Type": "ActionOutput", "OutputName": "Device Model"},
            "WFSerializationType": "WFTextTokenAttachment",
        },
    }
    return [
        _act("getdevicedetails", UUID=details, WFDeviceDetail="Device Model"),
        _act("conditional", GroupingIdentifier=group, WFControlFlowMode=0, WFCondition=99,
             WFInput=model, WFConditionalActionString="Mac"),
        *then,
        _act("conditional", GroupingIdentifier=group, WFControlFlowMode=1),
        *otherwise,
        _act("conditional", GroupingIdentifier=group, WFControlFlowMode=2, UUID=_uuid()),
    ]


def notify(text: str) -> dict:
    return _act("notification", WFNotificationActionBody=text)


def workflow(actions: list[dict]) -> dict:
    return {
        "WFWorkflowClientVersion": "2607.0.2",
        "WFWorkflowMinimumClientVersion": 900,
        "WFWorkflowIcon": {"WFWorkflowIconStartColor": 4282601983, "WFWorkflowIconGlyphNumber": 59511},
        "WFWorkflowTypes": [],
        "WFWorkflowInputContentItemClasses": [],
        "WFWorkflowImportQuestions": [],
        "WFWorkflowActions": actions,
    }


def build(
    url: str,
    token: str,
    device: str,
    bt_id: str | None,
    bt_addr: str | None,
    scenes: dict[str, str] | None = None,
    routines: dict[str, str] | None = None,
) -> dict[str, dict]:
    dev = f"{url}/devices/{device}"
    shortcuts = {
        "Speakers on": [request(f"{dev}/power", token, True)],
        "Speakers off": [request(f"{dev}/power", token, False)],
        "Speakers": [request(f"{dev}/toggle", token)],
    }
    if bt_id and bt_addr:
        bt = f"{url}/bluetooth/{bt_id}"
        addr = bt_addr.lower().replace(":", "-")
        connect_mac = (
            f"for i in 1 2 3 4 5; do {BLUEUTIL} --connect {addr} && exit 0; sleep 2; done; exit 1"
        )
        shortcuts["Movie mode"] = if_mac(
            [
                comment("Enciende, el servidor suelta el parlante y la Mac se conecta"),
                request(f"{dev}/power", token, True),
                _act("delay", WFDelayTime=3),
                request(f"{bt}/disconnect", token),
                shell(connect_mac),
            ],
            [notify("Movie mode solo funciona en la Mac")],
        )
        shortcuts["Music mode"] = [
            request(f"{dev}/power", token, True),
            *if_mac([shell(f"{BLUEUTIL} --disconnect {addr}; sleep 1")], []),
            request(f"{bt}/connect", token),
        ]
    # Un atajo por escena: una sola petición, la lógica vive en el backend
    for scene, label in (scenes or {}).items():
        shortcuts[label] = [request(f"{url}/scenes/{scene}", token)]
    # Una rutina elige la escena según la hora (p. ej. noche o día con el mismo sticker)
    for routine, label in (routines or {}).items():
        shortcuts[label] = [request(f"{url}/routines/{routine}", token)]
    return {name: workflow(actions) for name, actions in shortcuts.items()}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", required=True, help="URL base del backend, p. ej. http://192.168.1.20:8000")
    ap.add_argument("--device", required=True, help="id del enchufe en devices.yaml")
    ap.add_argument("--bt-id", help="id en la sección bluetooth de devices.yaml")
    ap.add_argument("--bt-address", help="dirección Bluetooth del parlante")
    ap.add_argument("--out", required=True, type=Path, help="carpeta de salida")
    ap.add_argument("--only", nargs="*", help="genera solo estos atajos")
    ap.add_argument(
        "--scene",
        action="append",
        default=[],
        metavar="ESCENA=NOMBRE",
        help="atajo que ejecuta una escena, p. ej. --scene charly=Peluche (repetible)",
    )
    ap.add_argument(
        "--routine",
        action="append",
        default=[],
        metavar="RUTINA=NOMBRE",
        help="atajo que ejecuta una rutina por horario, p. ej. --routine cama=Cama (repetible)",
    )
    args = ap.parse_args()

    token = os.environ.get("SELFROOMHUB_TOKEN")
    if not token:
        sys.exit("Define SELFROOMHUB_TOKEN en el entorno")

    args.out.mkdir(parents=True, exist_ok=True)
    scenes = dict(item.split("=", 1) for item in args.scene)
    routines = dict(item.split("=", 1) for item in args.routine)
    built = build(
        args.url.rstrip("/"), token, args.device, args.bt_id, args.bt_address, scenes, routines
    )
    for name, wf in built.items():
        if args.only and name not in args.only:
            continue
        unsigned = args.out / f"{name}.unsigned.shortcut"
        plistlib.dump(wf, unsigned.open("wb"), fmt=plistlib.FMT_BINARY)
        subprocess.run(
            ["shortcuts", "sign", "--mode", "people-who-know-me", "--input", unsigned,
             "--output", args.out / f"{name}.shortcut"],
            check=True, capture_output=True,
        )
        unsigned.unlink()
        print(args.out / f"{name}.shortcut")


if __name__ == "__main__":
    main()
