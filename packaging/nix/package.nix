# SPDX-FileCopyrightText: 2021-2026 Libre Computer Project contributors
# SPDX-License-Identifier: GPL-2.0-only
# libretech-wiring-tool: `make` (the overlays, dt.deps) and `make install` into $out/share/libretech-wiring-tool,
# the install root the .deb puts at /opt/librecomputer/libretech-wiring-tool. lgpio and ldto cd to their own
# directory, so $out/bin holds wrappers that exec them there, with what they run on PATH.
{ lib, stdenv, makeWrapper, dtc, python3, bash, libgpiod, coreutils, gnugrep, gnused, gawk, findutils, util-linux
, diffutils, src, version }:
stdenv.mkDerivation {
  pname = "libretech-wiring-tool";
  inherit version src;
  nativeBuildInputs = [ makeWrapper dtc python3 ];
  buildInputs = [ bash python3 ];
  buildFlags = [ "all" ];
  enableParallelBuilding = true;
  dontConfigure = true;
  installPhase = ''
    runHook preInstall
    make install PREFIX=$out/share/libretech-wiring-tool
    mkdir -p $out/bin
    for t in lgpio ldto; do
      makeWrapper $out/share/libretech-wiring-tool/$t $out/bin/$t --prefix PATH : ${lib.makeBinPath [
        libgpiod dtc python3 coreutils gnugrep gnused gawk findutils util-linux diffutils ]}
    done
    runHook postInstall
  '';
  doInstallCheck = true;
  installCheckPhase = ''
    for t in gpioset gpioget gpioinfo; do test -x ${libgpiod}/bin/$t || { echo "libgpiod has no $t" >&2; exit 1; }; done
    n=$(find $out/share/libretech-wiring-tool/libre-computer -name '*.dtbo' | wc -l)
    echo "overlays: $n"
    test "$n" -gt 0
    test -f $out/share/libretech-wiring-tool/libre-computer/aml-s905x-cc/gpio.map
  '';
  meta = {
    description = "Libre Computer wiring tool: lgpio, ldto and the board device-tree overlays";
    homepage = "https://github.com/libre-computer-project/libretech-wiring-tool";
    license = lib.licenses.gpl2Only;
    platforms = lib.platforms.linux;
    mainProgram = "ldto";
  };
}
