export function mixedDistributionIsValid(distribution: { EASY: number; MEDIUM: number; TOUGH: number }, total: number) {
  return Object.values(distribution).every(value => Number.isInteger(value) && value >= 0) &&
    Object.values(distribution).reduce((sum, value) => sum + value, 0) === total;
}

export function activePlacoNotice(mode?: string) {
  return mode === "ACTIVE_ASSESSMENT"
    ? "Placo can provide conceptual guidance during an active assessment, but cannot reveal the answer."
    : null;
}
