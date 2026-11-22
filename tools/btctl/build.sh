#!/usr/bin/env bash
# Compila BtCtl.java a build/btctl.dex (se ejecuta en la Mac / máquina de desarrollo).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
BREW="$(brew --prefix)"
ANDROID_HOME="${ANDROID_HOME:-$BREW/share/android-commandlinetools}"
JAVAC="$BREW/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home/bin/javac"
ANDROID_JAR="$ANDROID_HOME/platforms/android-36/android.jar"
D8="$ANDROID_HOME/build-tools/36.0.0/d8"

OUT="$HERE/build"
rm -rf "$OUT"
mkdir -p "$OUT/classes"

"$JAVAC" -nowarn -source 11 -target 11 -cp "$ANDROID_JAR" -d "$OUT/classes" "$HERE/BtCtl.java"
"$D8" --lib "$ANDROID_JAR" --output "$OUT" "$OUT"/classes/*.class
mv "$OUT/classes.dex" "$OUT/btctl.dex"

echo "Generado: $OUT/btctl.dex"
