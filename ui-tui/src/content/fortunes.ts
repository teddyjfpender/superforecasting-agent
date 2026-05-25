const FORTUNES = [
  'separate the base rate from the story before moving probability',
  'write the resolution criteria before researching the question',
  'track what would change your mind before looking for more evidence',
  'fresh evidence matters less when the reference class is unstable',
  'wide uncertainty honestly reported beats false precision',
  'score every resolved forecast before trusting the next one',
  'look for the missing denominator before accepting a trend',
  'compare your inside view with the market before updating',
  'a stale forecast is a standing position with hidden risk',
  'postmortems are part of the model, not paperwork'
]

const LEGENDARY = [
  'rare calibration note: your next miss teaches the next prior',
  'rare calibration note: evidence quality is part of the probability',
  'rare calibration note: update size should match surprise'
]

const hash = (s: string) => [...s].reduce((h, c) => Math.imul(h ^ c.charCodeAt(0), 16777619), 2166136261) >>> 0

const fromScore = (n: number) => {
  const rare = n % 20 === 0
  const bag = rare ? LEGENDARY : FORTUNES

  return `${rare ? 'CAL' : 'P'} ${bag[n % bag.length]}`
}

export const randomFortune = () => fromScore(Math.floor(Math.random() * 0x7fffffff))
export const dailyFortune = (seed: null | string) => fromScore(hash(`${seed || 'anon'}|${new Date().toDateString()}`))
