import { SCORE_SCALE, scoreColor, scoreDots, STATUS_COLORS } from "../tokens";

test("score scale has six entries spanning 0..5", () => {
  expect(SCORE_SCALE).toHaveLength(6);
  expect(scoreColor(0)).toBe("#b0402b");
  expect(scoreColor(5)).toBe("#5f8a3f");
});

test("scoreColor clamps out-of-range values", () => {
  expect(scoreColor(-3)).toBe(SCORE_SCALE[0]);
  expect(scoreColor(99)).toBe(SCORE_SCALE[5]);
  expect(scoreColor(2.6)).toBe(scoreColor(3)); // rounds
});

test("scoreDots splits a value into filled + empty out of five", () => {
  expect(scoreDots(3)).toEqual({ filled: 3, empty: 2 });
  expect(scoreDots(0)).toEqual({ filled: 0, empty: 5 });
  expect(scoreDots(7)).toEqual({ filled: 5, empty: 0 });
});

test("status colors cover the document lifecycle states", () => {
  expect(STATUS_COLORS.indexed).toBe("#4a7a3c");
  expect(STATUS_COLORS.indexing).toBe("#a9711a");
  expect(STATUS_COLORS.failed).toBe("#a4442e");
});
