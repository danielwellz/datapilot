import { cohortScale } from './cohort-scale';

describe('cohortScale', () => {
  it('fits the domain to the rates, rounded outward to whole tenths', () => {
    const scale = cohortScale([0.287, 0.46, 0.735, 0.55]);
    expect([scale.from, scale.to]).toEqual([0.2, 0.8]);
  });

  it('splits the domain into five equal shades with exact bounds', () => {
    expect(cohortScale([0.287, 0.735]).steps).toEqual([
      { step: 1, from: 0.2, to: 0.32 },
      { step: 2, from: 0.32, to: 0.44 },
      { step: 3, from: 0.44, to: 0.56 },
      { step: 4, from: 0.56, to: 0.68 },
      { step: 5, from: 0.68, to: 0.8 },
    ]);
  });

  it.each([
    [0.2, 1],
    [0.287, 1],
    [0.3199, 1],
    [0.32, 2],
    [0.44, 3],
    [0.5599, 3],
    [0.56, 4],
    [0.68, 5],
    [0.735, 5],
    [0.8, 5],
  ])('puts %d in shade %d, a lower bound in the shade it starts', (rate, step) => {
    expect(cohortScale([0.287, 0.735]).stepOf(rate)).toBe(step);
  });

  it('keeps rates outside the domain in the end shades', () => {
    const scale = cohortScale([0.3, 0.5]);
    expect(scale.stepOf(0)).toBe(1);
    expect(scale.stepOf(1)).toBe(5);
  });

  it('spans the whole range when rates run from 0 to 100%', () => {
    const scale = cohortScale([0, 1]);
    expect([scale.from, scale.to]).toEqual([0, 1]);
    expect(scale.stepOf(0.19)).toBe(1);
    expect(scale.stepOf(0.2)).toBe(2);
  });

  it('widens a domain of one value to a tenth, downward at 100%', () => {
    expect([cohortScale([0.4, 0.4]).from, cohortScale([0.4, 0.4]).to]).toEqual([0.4, 0.5]);
    expect([cohortScale([1]).from, cohortScale([1]).to]).toEqual([0.9, 1]);
    expect(cohortScale([1]).stepOf(1)).toBe(5);
  });

  it('falls back to 0 to 100% without rates', () => {
    const scale = cohortScale([]);
    expect([scale.from, scale.to]).toEqual([0, 1]);
  });
});
