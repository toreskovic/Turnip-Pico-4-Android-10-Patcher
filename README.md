# Turnip Pico 4 / Android 10 Patcher

A Python script that patches a GameNative Turnip driver so it's compatible with Android 10 / the Pico 4 VR headset.

## "I don't care about the technobabble, I just want to play Beat Saber on my Pico 4"

A patched driver can be found under releases.

**NOTE: I can't vouch for the safety or compatibility of provided drivers. These drivers were NOT built by me and I'm not associated with driver developers nor GameNative. The only modification done by me was patching the driver with this tool.**

## What does this actually do?

The Pico 4 VR headset is still running Android 10. However, Turnip drivers provided with GameNative are compiled for newer versions of Android and depend on threading functions from the C11 standard that aren't natively present in Android 10. However, the Android NDK has its own implementation of those functions for Android 10. This tool patches the Turnip driver to use those NDK functions so it works on the Pico 4.

## Requirements

- Python **3.10+**
- Android NDK with the ARM64 API-29 compiler and `llvm-readelf`. Tested with
  **NDK 27.1.12297006**
- patchelf (see requirements.txt)
- Linux / WSL2

## Usage

### Setup venv and install patchelf

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

### Patch the Turnip driver with default options

```sh
source .venv/bin/activate
python convert.py /path/to/turnip-driver.zip
```

This creates `turnip-driver-Pico-A10-compat.zip` beside the input. The name shown
in GameNative is the original `meta.json` name plus `-Pico-A10-compat`.

## Options

The converter detects the NDK from `ANDROID_NDK_HOME`, `ANDROID_NDK_ROOT`, or
`NDK_HOME`, then SDK installations under `ANDROID_SDK_ROOT`, `ANDROID_HOME`,
`~/Android/sdk`, and `~/Library/Android/sdk`. Set an explicit path if needed:

```sh
python3 convert.py /path/to/Turnip-driver.zip \
  --ndk /path/to/android-ndk \
  --patchelf /path/to/patchelf
```

Without `--patchelf`, the converter first finds the executable supplied by the
`patchelf` package in the Python environment running the script, then falls back
to `PATH`.

```sh
python3 convert.py Driver.zip --output /existing/directory/Converted.zip
python3 convert.py Driver.zip --suffix=-Pico-Android10
python3 convert.py --help
```

The suffix affects both the default archive filename and the driver display name.
An explicit output path changes only the archive location/name.

After conversion, import the output .zip through GameNative's driver manager,
select the suffixed entry for the container, and enable **Use Adrenotools Turnip**.

## The setup this was tested with

- Pico 4
- GameNative v1.2.1 (the legacy-xr build)
- Beat Saber with a Quest 2 / Quest 3 GameNative compatibility config (you can check https://gamenative.app/compatibility/ and / or import configs from GameNative itself)

## License

The converter and wrapper source are MIT licensed (see `LICENSE`). The compiled
shim incorporates Android NDK code under its BSD-style license, copied into each
output ZIP from the NDK. Original driver files retain their original
licenses.
