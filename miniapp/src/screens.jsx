import React, { useEffect, useRef, useState } from 'react';
import { asDate, clock, formatDate, getPlan, nassCatalog, nassPlan, sessionPlan, videoProgram } from './demo.js';
import { YouTubeVideo } from './YouTubeVideo.jsx';

export function Progress({ exercises, results = [], current = -1 }) {
  return (
    <div className="segments" aria-hidden="true">
      {exercises.map((exercise, index) => (
        <span key={exercise.name} data-state={index === current ? 'current' : results[index]} />
      ))}
    </div>
  );
}

function doneCount(results) {
  return results.filter((result) => result === 'done').length;
}

export function Today({
  now, session, checkIn, dailyWorkoutGoal, recent, onStart, onRestart, onStartVideo, onNassLibrary, onCheckIn, onDiary,
}) {
  const plan = sessionPlan(session);
  const exerciseCount = plan.exercises.length;
  const step = session?.results.length;
  const isVideo = session?.mode === 'video';
  const checkInSummary = entryStats(checkIn ?? {});
  const hasCheckIn = Boolean(checkInSummary);
  const completed = checkIn?.workouts?.filter(
    (workout) => workout.mode === 'video' || workout.results?.includes('done'),
  ).length ?? 0;
  return (
    <section className="screen today">
      <p className="meta">{formatDate(now, { weekday: 'long', day: 'numeric', month: 'long' })}</p>
      <h1>Сегодня</h1>
      <div className="plan-card paper-border">
        <div className="row">
          <p className="meta">ЛФК за день · {Math.min(completed, dailyWorkoutGoal)}/{dailyWorkoutGoal}</p>
          {session && <span className="stamp">Не завершено</span>}
        </div>
        <h2>{isVideo ? videoProgram.title : plan.name}</h2>
        {isVideo ? <p className="plan-caption">Видео · {clock(videoProgram.duration_s)}</p> : <>
          <div className="plan-numbers">
            <div><strong>{exerciseCount}</strong><span>упражнений</span></div>
            {plan.minutes != null && <div><strong>{plan.minutes}</strong><span>минут, примерно</span></div>}
          </div>
          <Progress exercises={plan.exercises} results={session?.results} current={session ? step : -1} />
          <p className="plan-caption">
            {session
              ? `Шаг ${step + 1} из ${exerciseCount} · ${plan.exercises[step].name}`
              : <>Ориентир — 15–20 мин с разминкой, без просмотра всех видео.
                <br />По руководству нужны фитбол, коврик и полотенце.</>}
          </p>
        </>}
      </div>
      <button className="button primary wide" onClick={onStart}>
        {session ? 'Продолжить' : 'Начать ЛФК'} <span aria-hidden="true">→</span>
      </button>
      {!session && <button className="button wide check-in-button" onClick={onStartVideo}>
        <span className="pulse-mark" aria-hidden="true">▶</span>
        <span>Занятие по видео<small>{videoProgram.title} · {clock(videoProgram.duration_s)}</small></span>
      </button>}
      <button className="button wide check-in-button" onClick={onNassLibrary}>
        <span className="pulse-mark" aria-hidden="true">▤</span>
        <span>Библиотека видео NASS<small>Подвижность, силовые, растяжка и дыхание</small></span>
      </button>
      <button className="button wide check-in-button" onClick={onCheckIn}>
        <span className="pulse-mark" aria-hidden="true">✚</span>
        <span>
          {hasCheckIn ? 'Изменить самочувствие' : 'Отметить самочувствие'}
          <small>{hasCheckIn
            ? checkInSummary
            : 'Можно без занятия'}</small>
        </span>
        <span aria-hidden="true">+</span>
      </button>
      {session && !isVideo && <button className="text-button restart-button" onClick={onRestart}>Начать сначала</button>}
      {recent && !session && <button className="today-record" onClick={() => onDiary(recent.date)}>
        <span className="square-mark" aria-hidden="true">✓</span>
        <span>{[recent.label,
          recent.workout.mode === 'video' ? 'ЛФК по видео' : `${doneCount(recent.workout.results)} из ${recent.workout.results.length}`,
          workoutMinutes(recent.workout),
        ].filter(Boolean).join(' · ')}</span>
      </button>}
    </section>
  );
}

export function Exercise({ session, timer, onTimer, onComplete, onExit }) {
  const plan = sessionPlan(session);
  const exerciseCount = plan.exercises.length;
  const index = session.results.length;
  const exercise = plan.exercises[index];
  const isNass = plan.id === nassPlan.id;
  const guide = isNass && nassPlan.exercises.find(({ video }) => video.video_id === exercise.video?.video_id)?.video.guide;
  return (
    <section className="screen exercise">
      <div className="exercise-body" key={index}>
        <div className="row exercise-heading">
          <h1><strong>{index + 1}</strong> <span>из {exerciseCount}</span></h1>
          <button className="button compact" onClick={onExit}>Выйти</button>
        </div>
        <Progress exercises={plan.exercises} results={session.results} current={index} />
        {index === 0 && plan.advisory && <div className="warmup-advisory secondary-text">
          <p>{plan.advisory}</p>
          {isNass && <>
            <p>{nassCatalog.warmup.text}</p>
            <p>Двигайся плавно и без боли.</p>
            <a className="source-link" href={`${nassCatalog.guide_url}#page=${nassCatalog.warmup.page}`}
              target="_blank" rel="noopener">Разминка NASS</a>
          </>}
        </div>}
        <h2>{exercise.name}</h2>
        {guide && <dl className="instructions">
          <div>
            <dt className="meta">Повторы и удержание</dt>
            <dd><strong>{guide.repetitions} · {guide.hold_s} с на каждый повтор</strong></dd>
          </div>
          <div>
            <dt className="meta">Исходное положение</dt>
            <dd>{guide.position}</dd>
          </div>
          <div>
            <dt className="meta">Движение</dt>
            <dd>{guide.movement}</dd>
          </div>
        </dl>}
        {exercise.video && <>
          <YouTubeVideo video={exercise.video} label="Посмотреть технику · NASS"
            onOpen={() => onTimer('pause')} />
          {exercise.reps && <p className="secondary-text">Видео показывает движение. Дозировка указана в карточке.</p>}
        </>}
        {exercise.seconds ? (
          <Timer seconds={exercise.seconds} timer={timer} onAction={onTimer} />
        ) : exercise.reps && (
          <div className="reps"><strong>× {exercise.reps}</strong><span>
            {exercise.sides === 'both' ? 'на каждую сторону' : 'повторений'}
            {exercise.hold && <small>Удержание · {exercise.hold} с</small>}
          </span></div>
        )}
        {exercise.guideUrl ? (
          <a className="source-link" href={exercise.guideUrl} target="_blank" rel="noopener">
            Страница упражнения в руководстве NASS
          </a>
        ) : <dl className="instructions">
          <div>
            <dt className="meta">Исходное положение</dt>
            <dd>{exercise.position || 'Здесь будет исходное положение из твоего комплекса.'}</dd>
          </div>
          <div>
            <dt className="meta">Движение и дыхание</dt>
            <dd>{exercise.cue || 'Здесь будет короткая подсказка для этого упражнения.'}</dd>
            {exercise.breathing && <dd>{exercise.breathing}</dd>}
          </div>
        </dl>}
      </div>
      <footer className="action-bar">
        <button className="button compact" onClick={() => onComplete('skipped')}>Пропустить</button>
        <button className="button primary" onClick={() => onComplete('done')}>Готово <span aria-hidden="true">→</span></button>
      </footer>
    </section>
  );
}

export function NassLibrary({ onBack }) {
  const [selected, setSelected] = useState(null);
  return (
    <section className="screen nass-library">
      <button className="text-button" onClick={onBack}>‹ Сегодня</button>
      <p className="meta">NASS · Back to Action</p>
      <h1>Видео NASS</h1>
      <a className="source-link" href={nassCatalog.guide_url} target="_blank" rel="noopener">Руководство NASS</a>
      {nassCatalog.groups.map((group) => (
        <section className="library-group" key={group.id}>
          <h2>{group.title}</h2>
          <ul>
            {group.videos.map((video) => (
              <li key={video.video_id}>
                <button className="library-row" aria-expanded={selected === video.video_id}
                  onClick={() => setSelected(selected === video.video_id ? null : video.video_id)}>
                  <span>{video.title}</span><span className="meta">{clock(video.duration_s)}</span>
                </button>
                {selected === video.video_id && <YouTubeVideo video={video} label="Смотреть видео" />}
              </li>
            ))}
          </ul>
        </section>
      ))}
    </section>
  );
}

export function VideoSession({ onComplete, onExit }) {
  return (
    <section className="screen exercise">
      <div className="exercise-body">
        <div className="row exercise-heading">
          <p className="meta">Занятие по видео · {clock(videoProgram.duration_s)}</p>
          <button className="button compact" onClick={onExit}>Выйти</button>
        </div>
        <h2>{videoProgram.title}</h2>
        <p className="video-audience secondary-text">{videoProgram.audience}</p>
        <YouTubeVideo video={videoProgram} label="Смотреть занятие" />
      </div>
      <footer className="action-bar single">
        <button className="button primary" onClick={onComplete}>Завершить занятие</button>
      </footer>
    </section>
  );
}

function Timer({ seconds, timer, onAction }) {
  const remaining = Math.ceil(timer.remainingMs / 1000);
  const elapsed = 1 - remaining / seconds;
  const labels = { ready: 'Готов к старту', running: 'Идёт', paused: 'Пауза', finished: 'Время вышло' };
  return (
    <div className="timer paper-border">
      <div className="row">
        <p className="meta">Таймер · {seconds === 60 ? '1 мин' : `${seconds} сек`}</p>
        <span className="stamp" role="status">{labels[timer.status]}</span>
      </div>
      <output className="timer-digits" aria-live="off">{clock(remaining)}</output>
      <div className="timer-meter" aria-hidden="true"><div style={{ width: `${elapsed * 100}%` }} /></div>
      <div className="timer-actions">
        {timer.status === 'ready' && <button className="button primary" onClick={() => onAction('start')}>Старт</button>}
        {timer.status === 'running' && <button className="button" onClick={() => onAction('pause')}>Пауза</button>}
        {timer.status === 'paused' && <button className="button primary" onClick={() => onAction('start')}>Дальше</button>}
        {['paused', 'finished'].includes(timer.status) && <button className="button" onClick={() => onAction('reset')}>Заново</button>}
      </div>
    </div>
  );
}

export function Summary({ summary, note, setNote, onSave }) {
  const [videoMinutes, setVideoMinutes] = useState('');
  const isVideo = summary.mode === 'video';
  const plan = getPlan(summary.planId);
  const exercises = summary.exerciseNames?.map((name) => ({ name })) ?? plan.exercises;
  const completed = isVideo ? 0 : doneCount(summary.results);
  const skipped = isVideo ? 0 : summary.results.length - completed;
  return (
    <section className="screen summary">
      <form className="summary-body" id="summary-form" onSubmit={(event) => {
        event.preventDefault();
        onSave(videoMinutes);
      }}>
        <p className="meta">{summary.title ?? plan.name} · {formatDate(asDate(summary.date), { day: 'numeric', month: 'long' })}</p>
        <h1>Занятие<br />завершено</h1>
        {isVideo ? <label className="summary-note">
          <span>Длительность занятия в минутах <small>необязательно</small></span>
          <input type="number" inputMode="numeric" min="1" max="1440" value={videoMinutes}
            onChange={(event) => setVideoMinutes(event.target.value)} />
        </label> : <>
          <div className="stat-grid">
            <div className="stat stat-inverse"><strong>{completed}</strong><span>выполнено</span></div>
            <div className="stat paper-border"><strong>{skipped}</strong><span>пропущено</span></div>
          </div>
          <p className="stat stat-duration paper-border"><strong>{clock(summary.duration)}</strong><span>длительность</span></p>
          <Progress exercises={exercises} results={summary.results} />
          {skipped > 0 && <p className="secondary-text">Пропущено: {exercises
            .filter((_, index) => summary.results[index] === 'skipped')
            .map(({ name }) => name)
            .join(', ')}</p>}
        </>}
        <label className="summary-note">
          <span>Самочувствие после ЛФК <small>необязательно</small></span>
          <textarea rows="3" maxLength="500" value={note} onChange={(event) => setNote(event.target.value)} />
        </label>
      </form>
      <footer className="action-bar single">
        <button className="button primary" type="submit" form="summary-form">Готово</button>
      </footer>
    </section>
  );
}

function workoutMinutes(workout) {
  return workout?.duration != null ? `${Math.round(workout.duration / 60)} мин` : '';
}

function entryStats(entry) {
  const parts = [
    entry.pain != null && `боль ${entry.pain}`,
    entry.stiffness != null && `скованность ${entry.stiffness} мин`,
    entry.fatigue != null && `утомляемость ${entry.fatigue}/10`,
  ].filter(Boolean);
  return parts.join(' · ');
}

export function Diary({ diary, onDay, onToday, onReport }) {
  const dates = Object.keys(diary).sort().reverse();
  const formatMonth = (date) => formatDate(date, { month: 'long', year: 'numeric' });
  const firstMonth = formatMonth(dates.length ? asDate(dates[0]) : new Date());
  let month = firstMonth;
  return (
    <section className="screen diary">
      <p className="meta">{firstMonth}</p>
      <h1>Дневник</h1>
      {onReport && <button className="button wide diary-report" onClick={onReport}>Отчёт для ревматолога</button>}
      {dates.length === 0 && (
        <div className="empty">
          <div className="empty-icon paper-border" aria-hidden="true"><span>≡</span></div>
          <h2>Пока пусто</h2>
          <p>Здесь появятся занятия и записи самочувствия.</p>
          <button className="button primary wide" onClick={onToday}>К занятию <span aria-hidden="true">→</span></button>
        </div>
      )}
      {dates.map((date) => {
        const day = asDate(date);
        const entry = diary[date];
        const workout = entry.workouts?.at(-1);
        const stats = entryStats(entry);
        const skipped = workout?.results ? workout.results.length - doneCount(workout.results) : 0;
        const workoutInfo = [
          skipped > 0 && `пропущено ${skipped}`,
          workoutMinutes(workout),
          stats,
        ].filter(Boolean).join(' · ');
        const currentMonth = formatMonth(day);
        const showMonth = currentMonth !== month;
        month = currentMonth;
        return <React.Fragment key={date}>
          {showMonth && <h2 className="meta month-heading">{currentMonth}</h2>}
          <button className="diary-row" onClick={() => onDay(date)}>
            <span className="diary-date"><strong>{day.getDate()}</strong><small>{formatDate(day, { weekday: 'short' })}</small></span>
            <span className="diary-item">
              {workout ? <strong>{workout.mode === 'video' ? 'ЛФК по видео' :
                `${workout.planId === nassPlan.id ? 'NASS' : 'ЛФК'} · ${doneCount(workout.results)} из ${workout.results.length}`}</strong>
                : <span className="entry-tag">Только самочувствие</span>}
              <span className="secondary-text">
                {workoutInfo}
              </span>
            </span>
            <span className="chevron" aria-hidden="true">›</span>
          </button>
        </React.Fragment>;
      })}
    </section>
  );
}

export function DiaryDay({ date, entry, onBack, onEdit, onExerciseChange }) {
  const day = asDate(date);
  return (
    <section className="screen diary-day">
      <button className="text-button" onClick={onBack}>‹ Дневник</button>
      <p className="meta">{formatDate(day, { weekday: 'long' })}</p>
      <h1>{formatDate(day, { day: 'numeric', month: 'long' })}</h1>
      <div className="stat-grid check-in-stats">
        <div className="stat paper-border"><span className="meta">Боль</span><strong>{entry.pain ?? '—'}</strong><small>из 10</small></div>
        <div className="stat paper-border"><span className="meta">Скованность</span><strong>{entry.stiffness ?? '—'}</strong><small>мин</small></div>
        {entry.fatigue != null && <div className="stat paper-border">
          <span className="meta">Утомляемость</span><strong>{entry.fatigue}</strong><small>из 10</small>
        </div>}
      </div>
      {entry.checkInNote && <div className="diary-note"><p className="meta">Заметка</p><p>{entry.checkInNote}</p></div>}
      {entry.workouts?.length ? entry.workouts.map((workout, index) => {
        const plan = getPlan(workout.planId);
        const exerciseNames = workout.exerciseNames ?? plan.exercises.map(({ name }) => name);
        return (
          <article className="diary-workout" key={index}>
            {workout.note && <div className="diary-note"><p className="meta">Заметка после ЛФК</p><p>{workout.note}</p></div>}
            <div className="row">
              <h2>{workout.title ?? plan.name}</h2>
              <span className="meta">{workout.mode === 'video' ? workoutMinutes(workout)
                : `${doneCount(workout.results)}/${workout.results.length} · ${clock(workout.duration)}`}</span>
            </div>
            {workout.mode === 'video' ? <p className="secondary-text">Занятие по видео</p> : <ol className="exercise-list">
              {exerciseNames.map((name, exerciseIndex) => {
                const completed = workout.results[exerciseIndex] === 'done';
                return (
                  <li key={`${exerciseIndex}:${name}`}>
                    <label className="exercise-list-row">
                      <span className="meta" aria-hidden="true">{String(exerciseIndex + 1).padStart(2, '0')}</span>
                      <span>{name}</span>
                      {!completed && <span className="entry-tag" aria-hidden="true">Пропущено</span>}
                      <input type="checkbox" checked={completed}
                        onChange={(event) => onExerciseChange(index, exerciseIndex, event.currentTarget.checked)} />
                    </label>
                  </li>
                );
              })}
            </ol>}
          </article>
        );
      }) : (
        <div className="no-workout"><h2>В этот день занятия не было</h2><p>Есть только запись самочувствия.</p></div>
      )}
      <button className="button wide" onClick={onEdit}>Изменить запись</button>
    </section>
  );
}

export function Sheet({ title, children, onClose, closing = false }) {
  const ref = useRef(null);
  const closeCallback = useRef(onClose);
  closeCallback.current = onClose;
  const [dismissed, setDismissed] = useState(false);
  const leaving = dismissed || closing;
  useEffect(() => {
    const dialog = ref.current;
    dialog.showModal();
    return () => dialog.close();
  }, []);
  useEffect(() => {
    if (!leaving) return;
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const timeout = window.setTimeout(() => closeCallback.current(), reduced ? 0 : 180);
    return () => window.clearTimeout(timeout);
  }, [leaving]);
  return (
    <dialog
      className="sheet"
      ref={ref}
      data-closing={leaving || undefined}
      aria-labelledby="sheet-title"
      onCancel={(event) => { event.preventDefault(); setDismissed(true); }}
    >
      <div className="sheet-grip" aria-hidden="true" />
      <div className="row">
        <h2 id="sheet-title">{title}</h2>
        <button className="close-sheet" onClick={() => setDismissed(true)} aria-label="Закрыть">×</button>
      </div>
      {children}
    </dialog>
  );
}

function ScoreField({ label, value, onChange }) {
  return (
    <fieldset>
      <legend>{label}</legend>
      <p className="secondary-text">0 — нет · 10 — очень сильная</p>
      <div className="pain-grid">
        {Array.from({ length: 11 }, (_, score) => (
          <button key={score} type="button" aria-pressed={value === score} onClick={() => onChange(score)}>{score}</button>
        ))}
        <button type="button" className="reset-pain" onClick={() => onChange(null)}>Сброс</button>
      </div>
    </fieldset>
  );
}

export function CheckIn({ date, entry, fatigueOnly, issue, onSave, onClose }) {
  const [pain, setPain] = useState(entry?.pain ?? null);
  const [stiffness, setStiffness] = useState(entry?.stiffness ?? '');
  const [fatigue, setFatigue] = useState(entry?.fatigue ?? null);
  const [showAll, setShowAll] = useState(!fatigueOnly);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  function adjustStiffness(amount) {
    setStiffness((value) => Math.max(0, Math.min(1440, Number(value) + amount)));
  }
  return (
    <Sheet title="Самочувствие" closing={saved} onClose={onClose}>
      <p className="meta">{formatDate(asDate(date), { day: 'numeric', month: 'long' })} · отметки необязательны</p>
      {issue}
      <form onSubmit={async (event) => {
        event.preventDefault();
        if (saving || saved) return;
        setSaving(true);
        try {
          setSaved(await onSave({ pain, stiffness: stiffness === '' ? null : Number(stiffness), fatigue }));
        } finally {
          setSaving(false);
        }
      }}>
        {showAll && <>
          <ScoreField label="Боль" value={pain} onChange={setPain} />
          <div className="stiffness">
            <label htmlFor="stiffness">Утренняя скованность <small>в минутах</small></label>
            <div className="stiffness-controls">
              <button type="button" onClick={() => adjustStiffness(-5)} aria-label="Уменьшить на 5 минут">−</button>
              <input id="stiffness" type="number" inputMode="numeric" min="0" max="1440" value={stiffness}
                placeholder="—" onChange={(event) => setStiffness(event.target.value)} />
              <button type="button" onClick={() => adjustStiffness(5)} aria-label="Увеличить на 5 минут">+</button>
            </div>
          </div>
        </>}
        <ScoreField label="Утомляемость за день" value={fatigue} onChange={setFatigue} />
        {!showAll && <button className="text-button" type="button" onClick={() => setShowAll(true)}>Все отметки</button>}
        <button className="button primary wide" type="submit" disabled={saving || saved}>
          {saved ? 'Сохранено' : saving ? 'Сохраняем…' : 'Сохранить'}
        </button>
      </form>
    </Sheet>
  );
}
