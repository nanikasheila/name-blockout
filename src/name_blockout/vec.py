# SPDX-License-Identifier: GPL-3.0-or-later
"""Small 2D/3D vector helpers (plain tuples, no numpy: this runs in any Python)."""

from __future__ import annotations

import math
from collections.abc import Sequence

Vec2 = tuple[float, float]
Vec3 = tuple[float, float, float]


def add(a: Sequence[float], b: Sequence[float]) -> tuple[float, ...]:
    return tuple(x + y for x, y in zip(a, b))


def sub(a: Sequence[float], b: Sequence[float]) -> tuple[float, ...]:
    return tuple(x - y for x, y in zip(a, b))


def scale(a: Sequence[float], k: float) -> tuple[float, ...]:
    return tuple(x * k for x in a)


def dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def cross(a: Sequence[float], b: Sequence[float]) -> Vec3:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def norm(a: Sequence[float]) -> float:
    return math.sqrt(dot(a, a))


def unit(a: Sequence[float]) -> tuple[float, ...]:
    n = norm(a)
    if n < 1e-12:
        raise ValueError("zero vector")
    return tuple(x / n for x in a)


def bounds(points: Sequence[Sequence[float]]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def line_at_x(a: Sequence[float], b: Sequence[float], x: float) -> float:
    """The y of the line through a and b at x (a's y for a vertical line)."""
    dx = b[0] - a[0]
    if abs(dx) < 1e-9:
        return a[1]
    return a[1] + (x - a[0]) * (b[1] - a[1]) / dx


def point_line_distance(p: Sequence[float], a: Sequence[float], b: Sequence[float]) -> float:
    d = sub(b, a)
    n = norm(d)
    if n < 1e-12:
        return norm(sub(p, a))
    return abs(d[0] * (p[1] - a[1]) - d[1] * (p[0] - a[0])) / n


def box_iou(a: Sequence[float], b: Sequence[float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    area = lambda r: max(0.0, r[2] - r[0]) * max(0.0, r[3] - r[1])  # noqa: E731
    union = area(a) + area(b) - inter
    return inter / union if union > 0 else 0.0


def nelder_mead(fun, x0: Sequence[float], step: float | Sequence[float] = 0.5, iterations: int = 4000, tol: float = 1e-10):
    """Minimise `fun` from `x0` (Nelder–Mead). Returns (x, value)."""
    n = len(x0)
    steps = [step] * n if isinstance(step, (int, float)) else list(step)
    simplex = [list(map(float, x0))]
    for i in range(n):
        p = list(map(float, x0))
        p[i] += steps[i]
        simplex.append(p)
    values = [fun(p) for p in simplex]
    for _ in range(iterations):
        order = sorted(range(n + 1), key=lambda i: values[i])
        simplex = [simplex[i] for i in order]
        values = [values[i] for i in order]
        if abs(values[-1] - values[0]) <= tol * (1 + abs(values[0])):
            break
        centre = [sum(p[i] for p in simplex[:-1]) / n for i in range(n)]
        worst = simplex[-1]
        reflected = [c + (c - w) for c, w in zip(centre, worst)]
        fr = fun(reflected)
        if fr < values[0]:
            expanded = [c + 2 * (c - w) for c, w in zip(centre, worst)]
            fe = fun(expanded)
            simplex[-1], values[-1] = (expanded, fe) if fe < fr else (reflected, fr)
        elif fr < values[-2]:
            simplex[-1], values[-1] = reflected, fr
        else:
            contracted = [c + 0.5 * (w - c) for c, w in zip(centre, worst)]
            fc = fun(contracted)
            if fc < values[-1]:
                simplex[-1], values[-1] = contracted, fc
            else:
                best = simplex[0]
                for i in range(1, n + 1):
                    simplex[i] = [b + 0.5 * (p - b) for b, p in zip(best, simplex[i])]
                    values[i] = fun(simplex[i])
    i = min(range(n + 1), key=lambda k: values[k])
    return simplex[i], values[i]
