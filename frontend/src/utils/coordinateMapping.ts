// Homography helpers mirroring OpenCV's getPerspectiveTransform, used for the
// live calibration preview (projecting the battlefield grid onto the camera image)
// and client-side validation before the backend confirms.

export type Pt = [number, number];
export type Mat3 = number[]; // row-major 3x3

function solve(A: number[][], b: number[]): number[] {
  const n = b.length;
  const M = A.map((row, i) => [...row, b[i]]);
  for (let c = 0; c < n; c++) {
    let piv = c;
    for (let r = c + 1; r < n; r++) if (Math.abs(M[r][c]) > Math.abs(M[piv][c])) piv = r;
    [M[c], M[piv]] = [M[piv], M[c]];
    if (Math.abs(M[c][c]) < 1e-12) throw new Error('singular');
    for (let r = 0; r < n; r++) {
      if (r === c) continue;
      const f = M[r][c] / M[c][c];
      for (let k = c; k <= n; k++) M[r][k] -= f * M[c][k];
    }
  }
  return M.map((row, i) => row[n] / row[i]);
}

/** Homography mapping src[i] -> dst[i] for 4 point pairs. */
export function perspectiveTransform(src: Pt[], dst: Pt[]): Mat3 {
  const A: number[][] = [];
  const b: number[] = [];
  for (let i = 0; i < 4; i++) {
    const [x, y] = src[i];
    const [u, v] = dst[i];
    A.push([x, y, 1, 0, 0, 0, -u * x, -u * y]);
    b.push(u);
    A.push([0, 0, 0, x, y, 1, -v * x, -v * y]);
    b.push(v);
  }
  const h = solve(A, b);
  return [...h, 1];
}

export function applyH(H: Mat3, [x, y]: Pt): Pt {
  const w = H[6] * x + H[7] * y + H[8];
  return [(H[0] * x + H[1] * y + H[2]) / w, (H[3] * x + H[4] * y + H[5]) / w];
}

/** Mirrors backend validate_quad so the UI can warn before submitting. */
export function validateQuad(pts: Pt[], frame: [number, number]): string | null {
  if (pts.length !== 4) return 'Place all four corners.';
  const [w, h] = frame;
  let signed = 0;
  for (let i = 0; i < 4; i++) {
    const [x1, y1] = pts[i];
    const [x2, y2] = pts[(i + 1) % 4];
    signed += x1 * y2 - x2 * y1;
  }
  signed /= 2;
  if (Math.abs(signed) < 0.04 * w * h) return 'The selected area is too small - mark the whole play area.';
  if (signed < 0) return 'Corners are out of order. Go clockwise: top-left, top-right, bottom-right, bottom-left.';
  const crosses = pts.map((a, i) => {
    const b = pts[(i + 1) % 4];
    const c = pts[(i + 2) % 4];
    return (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]);
  });
  if (!(crosses.every((c) => c > 0) || crosses.every((c) => c < 0))) return 'The shape is not convex - edges cross.';
  for (let i = 0; i < 4; i++) {
    const p = pts[(i + 3) % 4];
    const c = pts[i];
    const n = pts[(i + 1) % 4];
    const v1 = [p[0] - c[0], p[1] - c[1]];
    const v2 = [n[0] - c[0], n[1] - c[1]];
    const cos = (v1[0] * v2[0] + v1[1] * v2[1]) / (Math.hypot(v1[0], v1[1]) * Math.hypot(v2[0], v2[1]));
    const ang = (Math.acos(Math.max(-1, Math.min(1, cos))) * 180) / Math.PI;
    if (ang < 25 || ang > 155) return `Corner ${i + 1} has an extreme angle (${ang.toFixed(0)}°). Point the camera more directly down.`;
  }
  return null;
}

/** Converts a pointer event to logical canvas coordinates. */
export function eventToLogical(e: { clientX: number; clientY: number }, el: HTMLElement, logicalW: number, logicalH: number): Pt {
  const r = el.getBoundingClientRect();
  return [((e.clientX - r.left) / r.width) * logicalW, ((e.clientY - r.top) / r.height) * logicalH];
}
