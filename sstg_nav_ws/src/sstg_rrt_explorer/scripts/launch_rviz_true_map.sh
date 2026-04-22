#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
WORKSPACE_ROOT="$(cd "${PKG_DIR}/../../.." && pwd)"
OVERLAY_PREFIX="${WORKSPACE_ROOT}/.rviz_fix_prefix"
RVIZ_RENDERING_SHARE="${OVERLAY_PREFIX}/share/rviz_rendering"
RESOURCE_INDEX_DIR="${OVERLAY_PREFIX}/share/ament_index/resource_index/packages"
SOURCE_MEDIA_DIR="/opt/ros/humble/share/rviz_rendering/ogre_media"
TARGET_MEDIA_DIR="${RVIZ_RENDERING_SHARE}/ogre_media"
FRAG_FILE="${TARGET_MEDIA_DIR}/materials/glsl120/indexed_8bit_image.frag"
MATERIAL_FILE="${TARGET_MEDIA_DIR}/materials/scripts/indexed_8bit_image.material"
RVIZ_CFG="${PKG_DIR}/rviz/rrt_ros2.rviz"

mkdir -p "${RESOURCE_INDEX_DIR}"
mkdir -p "${RVIZ_RENDERING_SHARE}"
: > "${RESOURCE_INDEX_DIR}/rviz_rendering"

if [[ ! -d "${TARGET_MEDIA_DIR}" ]]; then
  cp -a "${SOURCE_MEDIA_DIR}" "${TARGET_MEDIA_DIR}"
fi

python3 - <<'PY' "${FRAG_FILE}" "${MATERIAL_FILE}"
from pathlib import Path
import sys

frag_path = Path(sys.argv[1])
material_path = Path(sys.argv[2])

frag = frag_path.read_text()
frag = frag.replace('uniform sampler1D palette;', 'uniform sampler2D palette;')
frag = frag.replace(
    '  vec4 color = texture1D( palette, 0.999 * texture2D( eight_bit_image, UV ).x );',
    '  vec4 color = texture2D(\n'
    '    palette,\n'
    '    vec2(0.999 * texture2D(eight_bit_image, UV).x, 0.5)\n'
    '  );'
)
frag_path.write_text(frag)

material = material_path.read_text()
material = material.replace('texture test_20x20.png 1d', 'texture test_20x20.png 2d')
material_path.write_text(material)
PY

export AMENT_PREFIX_PATH="${OVERLAY_PREFIX}:${AMENT_PREFIX_PATH:-}"
exec rviz2 -d "${RVIZ_CFG}"
