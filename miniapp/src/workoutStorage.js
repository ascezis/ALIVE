import { useEffect, useRef, useState } from 'react';
import { sampleDiary } from './demo.js';

const demo = new URLSearchParams(window.location.search).get('demo');
export const emptyTimer = { status: 'ready', remainingMs: 0, endsAt: 0 };
const emptyState = { session: null, timer: emptyTimer, summary: null, diary: {} };
const demoState = demo == null ? null : {
  revision: 0,
  state: { ...emptyState, diary: demo === 'empty' ? {} : sampleDiary() },
};

let telegramScript;
function getTelegram() {
  if (window.Telegram?.WebApp) return Promise.resolve(window.Telegram.WebApp);
  const telegramLaunch = new URLSearchParams(window.location.hash.slice(1)).has('tgWebAppData');
  if (!telegramLaunch) return Promise.resolve(null);
  telegramScript ??= new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = 'https://telegram.org/js/telegram-web-app.js';
    script.onload = () => resolve(window.Telegram?.WebApp);
    script.onerror = () => {
      telegramScript = undefined;
      script.remove();
      reject(new Error('Telegram SDK could not load'));
    };
    document.head.append(script);
  });
  return telegramScript;
}

async function requestApi(path, method, payload, signal) {
  const telegram = await getTelegram();
  const headers = {};
  if (telegram?.initData) {
    headers['X-Telegram-Init-Data'] = telegram.initData;
    telegram.ready();
  }
  if (payload) headers['Content-Type'] = 'application/json';
  const response = await fetch(path, {
    method,
    headers,
    body: payload ? JSON.stringify(payload) : undefined,
    signal,
    cache: 'no-store',
  });
  if (!response.ok) throw new StorageError(response.status);
  return response.json();
}

function requestSnapshot(payload, signal) {
  return requestApi('/api/state', payload ? 'PUT' : 'GET', payload, signal);
}

export function prepareDiaryReport(period, signal) {
  return requestApi('/api/report', 'POST', period, signal);
}

class StorageError extends Error {
  constructor(status) {
    super(`State request failed: ${status}`);
    this.status = status;
  }
}

export function useWorkoutStorage() {
  const [snapshot, setSnapshot] = useState(demoState);
  const current = useRef(demoState);
  const writing = useRef(false);
  const [saving, setSaving] = useState(false);
  const [issue, setIssue] = useState(null);
  const [loadAttempt, setLoadAttempt] = useState(0);

  useEffect(() => {
    if (demoState) return;
    const controller = new AbortController();
    requestSnapshot(undefined, controller.signal).then((loaded) => {
      if (controller.signal.aborted) return;
      current.current = loaded;
      setSnapshot(loaded);
    }).catch((error) => {
      if (!controller.signal.aborted) {
        setIssue(error.status === 401 || error.status === 403
          ? { message: 'Открой ALIVE из Telegram под своим аккаунтом.' }
          : { message: 'Не удалось загрузить дневник.' });
      }
    });
    return () => controller.abort();
  }, [loadAttempt]);

  async function save(update) {
    if (writing.current || !current.current) return false;
    writing.current = true;
    setSaving(true);
    setIssue(null);
    try {
      const { revision, state } = current.current;
      const change = { revision, state: { ...state, ...update } };
      const saved = demoState ? change : await requestSnapshot(change);
      current.current = saved;
      setSnapshot(saved);
      return true;
    } catch (error) {
      if (error.status === 409) {
        setIssue({ message: 'Дневник уже изменён в другом окне. Обнови страницу перед изменением.', reload: true });
      } else if (error.status === 401 || error.status === 403) {
        setIssue({ message: 'Сеанс Telegram истёк. Открой ALIVE из бота заново.' });
      } else {
        setIssue({ message: 'Не удалось сохранить изменение. Повтори действие.' });
      }
      return false;
    } finally {
      writing.current = false;
      setSaving(false);
    }
  }

  function retryLoad() {
    setIssue(null);
    setLoadAttempt((attempt) => attempt + 1);
  }

  return {
    state: snapshot?.state, dailyWorkoutGoal: snapshot?.dailyWorkoutGoal ?? 1,
    saving, issue, save, retryLoad, isDemo: Boolean(demoState),
  };
}
