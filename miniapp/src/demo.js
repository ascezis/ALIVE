import { exercise_library, nass_catalog, video_sessions } from '../../src/lfk-spec.json';

const kneeRoll = exercise_library.find((exercise) => exercise.id === 'knee_rock');
export const videoProgram = video_sessions[0];
export const nassCatalog = nass_catalog;

export const nassPlan = {
  id: nassCatalog.program_id,
  name: nassCatalog.title,
  advisory: nassCatalog.warmup_advisory,
  exercises: nassCatalog.groups.find((group) => group.id === 'mobility').videos.map((video) => ({
    name: video.title,
    video,
    guideUrl: `${nassCatalog.guide_url}#page=${video.page}`,
  })),
};

// Older sessions and diary records can lack a saved copy of their exercise list.
const legacyPlan = {
  id: 'demo',
  name: 'Мобильность позвоночника',
  minutes: 20,
  exercises: [
    {
      name: 'Кошка — верблюд',
      reps: 10,
      position: 'На четвереньках, ладони под плечами, колени под тазом.',
      cue: 'В этой тестовой карточке показано, где будет подсказка по движению и дыханию.',
    },
    {
      name: 'Дыхание животом',
      seconds: 60,
      position: 'Лёжа на спине, колени согнуты.',
      cue: 'Запусти таймер, когда будешь готов. Отсчёт можно поставить на паузу.',
    },
    {
      name: kneeRoll.title,
      reps: kneeRoll.dose.reps,
      sides: kneeRoll.dose.sides,
      hold: kneeRoll.dose.hold_s,
      position: kneeRoll.start_position,
      cue: kneeRoll.movement,
      breathing: kneeRoll.breathing,
      video: kneeRoll.video,
    },
    { name: 'Потягивание лёжа', reps: 8 },
    { name: 'Удержание позы', seconds: 30 },
    { name: 'Растяжка у стены', reps: 6 },
    { name: 'Движение плечами', reps: 8 },
    { name: 'Дыхание лёжа', seconds: 45 },
  ],
};

export function getPlan(planId) {
  return planId === nassPlan.id ? nassPlan : legacyPlan;
}

export function sessionPlan(session) {
  return session ? (session.planSnapshot ?? getPlan(session.planId)) : nassPlan;
}

export function dayKey(date = new Date()) {
  const parts = [date.getFullYear(), date.getMonth() + 1, date.getDate()];
  return parts.map((part) => String(part).padStart(2, '0')).join('-');
}

export function asDate(key) {
  return new Date(`${key}T12:00:00`);
}

export function formatDate(date, options) {
  return new Intl.DateTimeFormat('ru-RU', options).format(date);
}

export function clock(seconds) {
  return [Math.floor(seconds / 60), seconds % 60]
    .map((part) => String(part).padStart(2, '0'))
    .join(':');
}

export function sampleDiary() {
  const now = new Date();
  const previous = (days) => dayKey(new Date(now.getFullYear(), now.getMonth(), now.getDate() - days));
  const allDone = nassPlan.exercises.map(() => 'done');
  const withSkip = nassPlan.exercises.map((_, index) => index === 5 ? 'skipped' : 'done');
  return {
    [previous(1)]: {
      pain: 3, stiffness: 30,
      workouts: [{ planId: nassPlan.id, results: allDone, duration: 21 * 60, note: '' }],
    },
    [previous(2)]: {
      pain: 4, stiffness: 40,
      workouts: [{ planId: nassPlan.id, results: withSkip, duration: 19 * 60, note: 'Пример заметки после занятия.' }],
    },
    [previous(3)]: { pain: 5, stiffness: 60, checkInNote: 'Пример заметки о самочувствии в день без ЛФК.' },
    [previous(4)]: {
      pain: 2, stiffness: 20,
      workouts: [{ planId: nassPlan.id, results: allDone, duration: 20 * 60, note: '' }],
    },
  };
}
