import React, { useEffect, useRef, useState } from 'react';
import { dayKey } from './demo.js';
import { Sheet } from './screens.jsx';
import { prepareDiaryReport } from './workoutStorage.js';

export function ReportSheet({ onClose }) {
  const [period, setPeriod] = useState(() => {
    const end = new Date();
    const start = new Date(end);
    start.setDate(end.getDate() - 29);
    return { start: dayKey(start), end: dayKey(end) };
  });
  const [download, setDownload] = useState(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const request = useRef(null);
  useEffect(() => () => request.current?.abort(), []);

  function update(field, value) {
    setPeriod({ ...period, [field]: value });
    setDownload(null);
    setError('');
  }

  async function prepare(event) {
    event.preventDefault();
    if (pending) return;
    const controller = new AbortController();
    request.current = controller;
    setPending(true);
    setError('');
    setDownload(null);
    try {
      const result = await prepareDiaryReport(period, controller.signal);
      setDownload({ ...result, expiresAt: Date.now() + result.expiresIn * 1000 });
    } catch (error) {
      if (!controller.signal.aborted) {
        setError(error.status === 401 || error.status === 403
          ? 'Открой ALIVE из Telegram заново.'
          : 'Не удалось подготовить PDF. Попробуй ещё раз.');
      }
    } finally {
      if (!controller.signal.aborted) setPending(false);
    }
  }

  function saveFile(event) {
    if (Date.now() >= download.expiresAt) {
      event.preventDefault();
      setDownload(null);
      setError('Ссылка истекла. Подготовь PDF ещё раз.');
      return;
    }
    const telegram = window.Telegram?.WebApp;
    if (window.location.protocol === 'https:' && telegram?.downloadFile && telegram.isVersionAtLeast('8.0')) {
      try {
        telegram.downloadFile({
          url: new URL(download.path, window.location.origin).href,
          file_name: download.filename,
        });
        event.preventDefault();
      } catch {
        // The browser's download link is still available.
      }
    }
  }

  return (
    <Sheet title="Отчёт для ревматолога" onClose={onClose}>
      <p>Боль, скованность, утомляемость, дни с ЛФК и заметки за выбранный период.</p>
      <form onSubmit={prepare}>
        <div className="report-dates">
          <label>С<input type="date" required value={period.start} max={period.end || undefined} disabled={pending}
            onChange={(event) => update('start', event.target.value)} /></label>
          <label>По<input type="date" required value={period.end} min={period.start || undefined} disabled={pending}
            onChange={(event) => update('end', event.target.value)} /></label>
        </div>
        {error && <p className="report-error" role="alert">{error}</p>}
        {download
          ? <a className="button primary wide report-download" href={download.path} download={download.filename}
            referrerPolicy="no-referrer" onClick={saveFile}>Скачать PDF</a>
          : <button className="button primary wide" type="submit" disabled={pending}>
            {pending ? 'Подготавливаем…' : 'Подготовить PDF'}
          </button>}
      </form>
    </Sheet>
  );
}
