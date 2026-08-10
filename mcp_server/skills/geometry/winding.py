"""Polygon winding helpers shared by the geometry-repair modules.

One place for the two orientation rules every repair tool needs, so the fix
for the winding-flip bug lives in exactly one spot instead of drifting copies:

- clockwise(): openstudio.joinAll()/openstudio.intersect() silently fail (or
  return an uninitialized result) for polygons in an alignFace local frame
  whose winding puts the normal at +z — they need the reversed order. This is
  ONLY correct in that local frame.

- match_normal(): Transformation.alignFace(face).inverse() maps the face's
  own outward normal to +z local, so polygons coming back from joinAll/
  intersect (normalized by clockwise() to -z local) map back to global space
  facing the OPPOSITE of the original surface. Re-applying clockwise() in the
  global frame — the original bug — only re-reverses loops whose global
  normal has z > 0: floors ended correct by double-flip, ceilings ended
  facing down, walls ended flipped 180°. Wrong-facing surfaces get wrong
  solar gains and film coefficients while Space.isEnclosedVolume() (winding-
  insensitive) and every area check stay silent. The correct rule is to
  orient the final global-frame loop against the mutated surface's own
  pre-mutation outward normal, which this implements.

gbxml_import keeps its own private clockwise() copy deliberately — the
existing one-way dependency direction (gbxml_import depends on geometry,
never the reverse) also means geometry modules never export to it.
"""
from __future__ import annotations

import openstudio


def clockwise(points: openstudio.Point3dVector) -> openstudio.Point3dVector:
    """Normalize an alignFace-local-frame polygon to the winding joinAll/intersect need.

    Reverses the loop iff its outward normal has z > 0. Only meaningful in the
    aligned local frame — applying this to a global-frame loop is the exact
    bug match_normal() exists to replace.
    """
    normal = openstudio.getOutwardNormal(points)
    if normal.is_initialized() and normal.get().z() > 0:
        return openstudio.reverse(points)
    return points


def match_normal(
    points: openstudio.Point3dVector, reference_normal: openstudio.Vector3d,
) -> openstudio.Point3dVector:
    """Orient a global-frame loop to face the same way as a reference outward normal.

    Reverses the loop iff its outward normal opposes reference_normal
    (dot < 0). A loop whose normal can't be computed is returned unchanged —
    callers' degenerate-area guards reject those anyway.
    """
    normal = openstudio.getOutwardNormal(points)
    if normal.is_initialized() and normal.get().dot(reference_normal) < 0:
        return openstudio.reverse(points)
    return points
