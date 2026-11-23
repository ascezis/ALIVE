import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import '@fontsource/oswald/cyrillic-700.css';
import '@fontsource/oswald/latin-700.css';
import '@fontsource/inter/cyrillic-400.css';
import '@fontsource/inter/cyrillic-600.css';
import '@fontsource/inter/latin-400.css';
import '@fontsource/inter/latin-600.css';
import { dayKey, nassPlan, sessionPlan, videoProgram } from './demo.js';
import { CheckIn, Diary, DiaryDay, Exercise, NassLibrary, Sheet, Summary, Today, VideoSession } from './screens.jsx';
import { emptyTimer, useWorkoutStorage } from './workoutStorage.js';
import { ReportSheet } from './ReportSheet.jsx';
import './styles.css';

function readyTimer(exercise) {
  return { status: 'ready', remainingMs: (exercise?.seconds ?? 0) * 1000, endsAt: 0 };
}

function updateTimer(timer, action, exercise, now) {
  if (action === 'reset') return readyTimer(exercise);
  if (action === 'start') {
    return { ...timer, status: 'running', endsAt: now + timer.remainingMs };
  }
  if (timer.status !== 'running') return timer;

  const remainingMs = Math.max(0, timer.endsAt - now);
  const status = remainingMs === 0 ? 'finished' : action === 'pause' ? 'paused' : 'running';
  return { ...timer, status, remainingMs };
}

function App() {
  const storage = useWorkoutStorage();
  if (!storage.state) return (
    <main className="app-frame">
      <section className="screen">
        <h1>ALIVE</h1>
        <p role="status">{storage.issue?.message ?? 'Загружаем дневник…'}</p>
        {storage.issue && <button className="button" onClick={storage.retryLoad}>Повторить</button>}
      </section>
    </main>
  );
  return <WorkoutApp storage={storage} />;
}

function SaveIssue({ issue }) {
  return issue && <div className="save-issue">
    <p role="alert">{issue.message}</p>
    {issue.reload && <button className="text-button" onClick={() => window.location.reload()}>Обновить страницу</button>}
  </div>;
}

function WorkoutApp({ storage }) {
  const { state: { session, timer, summary, diary }, save, saving, issue, isDemo } = storage;
  const [view, setView] = useState(summary ? 'summary' : 'today');
  const [dark, setDark] = useState(() => window.matchMedia('(prefers-color-scheme: dark)').matches);
  const [timerNow, setTimerNow] = useState(Date.now);
  const [note, setNote] = useState('');
  const [selectedDate, setSelectedDate] = useState(null);
  const [checkIn, setCheckIn] = useState(() => (
    new URLSearchParams(window.location.search).get('checkin') === 'fatigue'
      ? { date: dayKey(), fatigueOnly: true }
      : null
  ));
  const [showReport, setShowReport] = useState(false);
  const [confirmExit, setConfirmExit] = useState(false);
  const [confirmRestart, setConfirmRestart] = useState(false);
  const main = useRef(null);
  const activeSince = useRef(null);
  const today = new Date();
  const todayKey = dayKey(today);
  const yesterdayKey = dayKey(new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1));
  const todayWorkout = diary[todayKey]?.workouts?.at(-1);
  const yesterdayWorkout = diary[yesterdayKey]?.workouts?.at(-1);
  const recent = todayWorkout
    ? { date: todayKey, label: 'Сегодня', workout: todayWorkout }
    : yesterdayWorkout && { date: yesterdayKey, label: 'Вчера', workout: yesterdayWorkout };
  const inWorkout = view === 'exercise' || view === 'video' || view === 'summary';
  const diaryView = view === 'diary' || view === 'day';
  const visibleTimer = updateTimer(timer, 'tick', null, timerNow);

  useEffect(() => {
    const url = new URL(window.location.href);
    if (url.searchParams.get('checkin') === 'fatigue') {
      url.searchParams.delete('checkin');
      window.history.replaceState(window.history.state, '', url);
    } else if (url.searchParams.get('workout') === 'nass') {
      url.searchParams.delete('workout');
      window.history.replaceState(window.history.state, '', url);
      if (!summary && (!session || session.planId === nassPlan.id)) resume();
    }
  }, []);

  useLayoutEffect(() => {
    main.current.scrollTop = 0;
  }, [view, selectedDate]);

  useEffect(() => {
    document.documentElement.dataset.theme = dark ? 'dark' : 'light';
  }, [dark]);

  useEffect(() => {
    if (timer.status !== 'running') return;
    setTimerNow(Date.now());
    if (timer.endsAt <= Date.now()) return;
    const id = window.setInterval(() => {
      const now = Date.now();
      setTimerNow(now);
      if (now >= timer.endsAt) window.clearInterval(id);
    }, 100);
    return () => window.clearInterval(id);
  }, [timer.status, timer.endsAt]);

  async function startNass() {
    if (!await save({
      session: { planId: nassPlan.id, planSnapshot: nassPlan, startedAt: Date.now(), results: [] },
      timer: readyTimer(nassPlan.exercises[0]),
    })) return false;
    activeSince.current = Date.now();
    setView('exercise');
    return true;
  }

  function resume() {
    if (!session) {
      startNass();
      return;
    }
    if (session.mode !== 'video') activeSince.current = Date.now();
    setView(session.mode === 'video' ? 'video' : 'exercise');
  }

  async function startVideo() {
    if (await save({ session: { mode: 'video', startedAt: Date.now(), results: [] }, timer: emptyTimer })) {
      setView('video');
    }
  }

  async function completeVideo() {
    const completed = {
      mode: 'video',
      title: videoProgram.title,
      videoId: videoProgram.id,
      date: dayKey(new Date(session.startedAt)),
      duration: null,
    };
    if (!await save({ session: null, summary: completed, timer: emptyTimer })) return;
    setNote('');
    setView('summary');
  }

  function timerAction(action) {
    const exercise = sessionPlan(session).exercises[session.results.length];
    const now = Date.now();
    const next = updateTimer(timer, action, exercise, now);
    if (next !== timer) {
      setTimerNow(now);
      return save({ timer: next });
    }
  }

  function elapsedAt(now) {
    return (session.elapsedMs ?? 0) + Math.max(0, now - (activeSince.current ?? now));
  }

  async function leaveSession() {
    if (session.mode !== 'video') {
      const now = Date.now();
      if (!await save({
        session: { ...session, elapsedMs: elapsedAt(now) },
        timer: updateTimer(timer, 'pause', null, now),
      })) return;
      activeSince.current = null;
    }
    setConfirmExit(false);
    setView('today');
  }

  async function record(result) {
    const selectedPlan = sessionPlan(session);
    const exercises = selectedPlan.exercises;
    const results = [...session.results, result];
    const now = Date.now();
    const elapsedMs = elapsedAt(now);
    if (results.length < exercises.length) {
      if (await save({ session: { ...session, results, elapsedMs }, timer: readyTimer(exercises[results.length]) })) {
        activeSince.current = now;
      }
      return;
    }
    const completed = {
      results,
      planId: session.planId,
      title: selectedPlan.name,
      exerciseNames: exercises.map(({ name }) => name),
      date: dayKey(new Date(session.startedAt)),
      duration: Math.round(elapsedMs / 1000),
    };
    if (!await save({ session: null, summary: completed, timer: emptyTimer })) return;
    activeSince.current = null;
    setNote('');
    setView('summary');
  }

  async function saveSummary(videoMinutes) {
    const previous = diary[summary.date];
    if (!await save({
      summary: null,
      diary: {
        ...diary,
        [summary.date]: {
          ...previous,
          workouts: [...(previous?.workouts ?? []), {
            ...summary,
            duration: summary.mode === 'video' && videoMinutes !== '' ? Number(videoMinutes) * 60 : summary.duration,
            note: note.trim(),
          }],
        },
      },
    })) return;
    setView('today');
  }

  async function saveCheckIn(entry) {
    const { date } = checkIn;
    const previous = diary[date];
    const remove = entry.pain == null && entry.stiffness == null && entry.fatigue == null && !previous?.workouts?.length;
    const next = { ...diary, [date]: { ...previous, ...entry } };
    if (remove) delete next[date];
    if (!await save({ diary: next })) return false;
    if (view === 'day' && remove) setView('diary');
    return true;
  }

  function selectDay(date) {
    setSelectedDate(date);
    setView('day');
  }

  function changeExerciseResult(workoutIndex, exerciseIndex, checked) {
    const day = diary[selectedDate];
    const workout = day.workouts[workoutIndex];
    const results = workout.results.with(exerciseIndex, checked ? 'done' : 'skipped');
    const workouts = day.workouts.with(workoutIndex, { ...workout, results });
    return save({ diary: { ...diary, [selectedDate]: { ...day, workouts } } });
  }

  return (
    <div className="app-frame">
      <header className="app-header">
        <span className="wordmark">ALIVE <span>ЛФК</span></span>
        <button className="theme-switch" onClick={() => setDark(!dark)}
          aria-label={dark ? 'Включить светлую тему' : 'Включить тёмную тему'}>
          <span aria-hidden="true">{dark ? '☀' : '☾'}</span>
        </button>
      </header>
      {!checkIn && !confirmRestart && !confirmExit && <SaveIssue issue={issue} />}
      <main ref={main} aria-busy={saving} className={`app-main ${inWorkout ? 'app-main-fixed' : ''}`}>
        {view === 'today' && <Today now={today} session={session} checkIn={diary[todayKey]}
          recent={recent} onStart={resume} onRestart={() => setConfirmRestart(true)}
          onNassLibrary={() => setView('nass-library')}
          onStartVideo={startVideo} onCheckIn={() => setCheckIn({ date: todayKey })} onDiary={selectDay} />}
        {view === 'exercise' && session && <Exercise session={session} timer={visibleTimer} onTimer={timerAction}
          onComplete={record} onExit={() => setConfirmExit(true)} />}
        {view === 'video' && <VideoSession onComplete={completeVideo} onExit={() => setConfirmExit(true)} />}
        {view === 'nass-library' && <NassLibrary onBack={() => setView('today')} />}
        {view === 'summary' && summary && <Summary summary={summary} note={note} setNote={setNote} onSave={saveSummary} />}
        {view === 'diary' && <Diary diary={diary} onDay={selectDay} onToday={() => setView('today')}
          onReport={isDemo ? undefined : () => setShowReport(true)} />}
        {view === 'day' && diary[selectedDate] && <DiaryDay date={selectedDate} entry={diary[selectedDate]}
          onBack={() => setView('diary')} onEdit={() => setCheckIn({ date: selectedDate })}
          onExerciseChange={changeExerciseResult} />}
      </main>
      {!inWorkout && <nav className="navigation" aria-label="Разделы приложения" data-tab={diaryView ? 'diary' : 'today'}>
        <button aria-current={!diaryView ? 'page' : undefined} onClick={() => setView('today')}>
          <span className="nav-icon" aria-hidden="true">☼</span> Сегодня
        </button>
        <button aria-current={diaryView ? 'page' : undefined} onClick={() => setView('diary')}>
          <span className="nav-icon" aria-hidden="true">▤</span> Дневник
        </button>
      </nav>}
      {checkIn && <CheckIn date={checkIn.date} entry={diary[checkIn.date]} fatigueOnly={checkIn.fatigueOnly}
        issue={<SaveIssue issue={issue} />} onSave={saveCheckIn} onClose={() => setCheckIn(null)} />}
      {showReport && <ReportSheet onClose={() => setShowReport(false)} />}
      {confirmRestart && <Sheet title="Начать сначала?" onClose={() => setConfirmRestart(false)}>
        <p>Отметки текущего занятия сбросятся. Откроется первое упражнение комплекса NASS.</p>
        <SaveIssue issue={issue} />
        <button className="button primary wide" disabled={saving} onClick={async () => {
          if (await startNass()) setConfirmRestart(false);
        }}>Начать сначала</button>
        <button className="button wide" onClick={() => setConfirmRestart(false)}>Отмена</button>
      </Sheet>}
      {confirmExit && <Sheet title="Выйти из занятия?" onClose={() => setConfirmExit(false)}>
        <p>{session.mode === 'video'
          ? 'К этому занятию можно вернуться через «Продолжить». Позицию видео нужно выбрать в плеере.'
          : isDemo ? 'Нажми «Продолжить», чтобы вернуться к этому упражнению в демо.'
            : 'Нажми «Продолжить», чтобы вернуться к этому упражнению даже после закрытия приложения.'}</p>
        <SaveIssue issue={issue} />
        <button className="button primary wide" disabled={saving} onClick={leaveSession}>Выйти и сохранить</button>
        <button className="button wide" onClick={() => setConfirmExit(false)}>Остаться</button>
      </Sheet>}
    </div>
  );
}

createRoot(document.getElementById('root')).render(<App />);
