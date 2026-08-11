"""Polygon winding-order helpers shared by the geometry-repair tools.

OpenStudio's polygon operations (`joinAll`, `intersects`/`intersect`) are
winding-order sensitive and fail *silently* on the "wrong" order — returning
False or an empty result for correctly-overlapping polygons, with no error
raised. Both callers therefore have to normalize winding before handing
polygons over, and restore a sensible winding afterward.

These two jobs need two different rules, which is why they are two functions:

- `normalize_local_frame_winding` is for polygons that have been pushed through
  `Transformation.alignFace(...).inverse()` into a local frame where the surface
  lies in the z~0 plane and its outward normal is +/-Z. There, testing the sign
  of the normal's z component is exactly the winding test, and this is the form
  `joinAll`/`intersect` expect. It is ONLY valid in that local frame.

- `align_to_reference_normal` is for polygons already transformed BACK to global
  coordinates, where the surface's outward normal can point any direction. There
  the local-frame z-sign rule is meaningless: it would force every horizontal
  surface to face downward (silently flipping a RoofCeiling) and leave vertical
  walls in whatever order the polygon operation happened to emit. Use this
  instead, passing the original surface's outward normal captured before
  mutation, so the rebuilt polygon keeps the orientation it started with.

Kept here rather than duplicated per module so there is one definition to reason
about, and placed under `geometry` so `gbxml_import` can import it without
inverting this project's one-way geometry <- gbxml_import dependency direction.
"""
from __future__ import annotations

import openstudio


def normalize_local_frame_winding(
    points: openstudio.Point3dVector,
) -> openstudio.Point3dVector:
    """Normalize a local-frame (z~0) polygon to the winding OpenStudio ops expect.

    Precondition: `points` is in an `alignFace` local frame, so its outward normal
    is essentially +/-Z. Reversing on a positive z normal yields the clockwise
    convention `openstudio.joinAll()` and `openstudio.intersect()` require.

    Do NOT call this on global-coordinate polygons — see this module's docstring
    and `align_to_reference_normal`.
    """
    normal = openstudio.getOutwardNormal(points)
    if normal.is_initialized() and normal.get().z() > 0:
        return openstudio.reverse(points)
    return points


def align_to_reference_normal(
    points: openstudio.Point3dVector, reference_normal: openstudio.Vector3d,
) -> openstudio.Point3dVector:
    """Orient a global-coordinate polygon to face the same way as `reference_normal`.

    Compares the polygon's own outward normal against the reference (typically the
    original surface's normal, captured before it was mutated) and reverses the
    vertex order when they oppose. Works for any orientation — walls, sloped
    surfaces, roofs — because it never assumes the normal is axis-aligned.

    Leaves the order untouched when the polygon's normal can't be computed: with
    no reliable normal to compare, reversing would be an arbitrary guess.
    """
    normal = openstudio.getOutwardNormal(points)
    if not normal.is_initialized():
        return points
    if normal.get().dot(reference_normal) < 0:
        return openstudio.reverse(points)
    return points
