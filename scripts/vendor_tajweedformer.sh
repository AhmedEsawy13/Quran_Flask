#!/usr/bin/env bash
# Vendor @quran-lab/tajweedformer <version> into static/vendor/tajweedformer-<version>/ (no bundler on the Flask pages).
# After it: update the import map in templates/index.html and the version in static/vendor/*/README.md.
set -euo pipefail
version="${1:?usage: scripts/vendor_tajweedformer.sh <version>}"
root="$(cd "$(dirname "$0")/.." && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
(cd "$tmp" && npm pack "@quran-lab/tajweedformer@${version}" --silent && mkdir x && tar -xzf ./*.tgz -C x)
dest="$root/static/vendor/tajweedformer-${version}"
rm -rf "$dest"; mkdir -p "$dest/dist"
cp -R "$tmp/x/package/web" "$dest/web"
cp "$tmp"/x/package/dist/*.mjs "$tmp"/x/package/dist/*.wasm "$dest/dist/"
cp "$tmp/x/package/LICENSE" "$tmp/x/package/CHANGELOG.md" "$dest/"
echo "vendored into $dest"
