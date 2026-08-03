[app]

title = TG Stories
package.name = tgstories
package.domain = org.maaf

source.dir = .
source.include_exts = py,png,jpg,jpeg,ttf,atlas
source.include_patterns = assets/*

version = 1.0

# Dependency notes:
#   - Python pinned to 3.12: default is 3.14 and Kivy cannot build on it
#   - arabic_reshaper and bidi are vendored into the app source,
#     because buildozer silently drops pip version pins
#   - cryptg intentionally excluded (needs a C compiler)
requirements = python3==3.12.11,kivy,pyjnius,android,telethon,pyaes,rsa,pyasn1,setuptools

orientation = portrait
fullscreen = 0

android.permissions = INTERNET,ACCESS_NETWORK_STATE,WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE

android.api = 34

# API 26 is required, not optional: Bionic only declares setgrent/getgrent/
# endgrent from API 26. CPython's configure finds the symbols in libc.so and
# defines HAVE_GETGRENT, then grpmodule.c fails with -Werror because grp.h
# does not declare them below 26. arm64-only means every target device is
# Android 8+ anyway.
android.minapi = 26
android.ndk_api = 26

# p4a declares MIN_NDK_VERSION=25 and MAX_NDK_VERSION=25, but buildozer
# reads RECOMMENDED_NDK_VERSION ("28c") and downloads that. r28c's clang
# rejects '-print-multi-os-directory', breaking configure. Pin to 25.
android.ndk = 25b

# Single architecture = much faster build, covers most phones since 2017
android.archs = arm64-v8a

android.allow_backup = False
android.accept_sdk_license = True


[buildozer]

log_level = 2
warn_on_root = 0
