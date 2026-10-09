/** Number of shades in the heatmap's color scale. */
export const HEAT_STEPS = 5;

/** One shade of the scale and the retention it covers. */
export interface HeatStep {
  /** 1 (lowest) to {@link HEAT_STEPS}. */
  step: number;
  /** Fractions: 0.2 is 20%. The lower bound is included, the upper only in the last step. */
  from: number;
  to: number;
}

/**
 * A color scale fitted to the retention rates shown. Rates of real cohorts
 * sit in a narrow band (about 30% to 75%), so a 0 to 100% scale would paint
 * nearly every cell in one or two shades.
 */
export interface CohortScale {
  /** The domain, rounded outward to whole 10% steps. */
  from: number;
  to: number;
  steps: readonly HeatStep[];
  /** The shade of a rate, 1 to {@link HEAT_STEPS}; rates outside the domain take the end shades. */
  stepOf(rate: number): number;
}

// Rates are compared in basis points, so bounds such as 32% are exact rather
// than 0.31999999999999995.
const BASIS = 10_000;
const TENTH = BASIS / 10;

/** Fits {@link HEAT_STEPS} equal shades to the lowest and highest rate, widened to whole tenths. */
export function cohortScale(rates: readonly number[]): CohortScale {
  const points = rates.map((rate) => Math.round(rate * BASIS));
  let low = points.length === 0 ? 0 : Math.floor(Math.min(...points) / TENTH) * TENTH;
  let high = points.length === 0 ? BASIS : Math.ceil(Math.max(...points) / TENTH) * TENTH;
  if (high === low) {
    // Every rate is the same whole tenth: give the scale one tenth of width.
    if (high < BASIS) {
      high += TENTH;
    } else {
      low -= TENTH;
    }
  }
  const span = high - low;
  const steps = Array.from({ length: HEAT_STEPS }, (_, index) => ({
    step: index + 1,
    from: (low + (span * index) / HEAT_STEPS) / BASIS,
    to: (low + (span * (index + 1)) / HEAT_STEPS) / BASIS,
  }));
  return {
    from: low / BASIS,
    to: high / BASIS,
    steps,
    stepOf: (rate) => {
      const point = Math.round(rate * BASIS);
      const step = Math.floor(((point - low) * HEAT_STEPS) / span) + 1;
      return Math.min(Math.max(step, 1), HEAT_STEPS);
    },
  };
}
