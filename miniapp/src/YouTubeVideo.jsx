import React, { useState } from 'react';

export function YouTubeVideo({ video, label, onOpen }) {
  const [opened, setOpened] = useState(false);
  const watchUrl = new URL('https://www.youtube.com/watch');
  watchUrl.searchParams.set('v', video.video_id);
  const embedUrl = new URL(`https://www.youtube-nocookie.com/embed/${video.video_id}`);
  embedUrl.searchParams.set('playsinline', '1');
  if (video.start_s != null) {
    watchUrl.searchParams.set('t', `${video.start_s}s`);
    embedUrl.searchParams.set('start', video.start_s);
  }

  function openPlayer() {
    onOpen?.();
    setOpened(true);
  }

  function openYouTube(event) {
    onOpen?.();
    const webApp = window.Telegram?.WebApp;
    if (webApp?.openLink) {
      event.preventDefault();
      webApp.openLink(watchUrl.href);
    }
  }

  return (
    <div className="youtube-video">
      {opened ? (
        <iframe className="youtube-player" src={embedUrl.href} title={video.title}
          referrerPolicy="strict-origin-when-cross-origin" allow="encrypted-media; picture-in-picture"
          allowFullScreen />
      ) : (
        <button className="video-preview paper-border" onClick={openPlayer}>
          <span className="play-symbol" aria-hidden="true">▶</span>
          <span>{label}</span>
        </button>
      )}
      <div className="video-links">
        {opened && <button className="text-button" onClick={() => setOpened(false)}>Скрыть видео</button>}
        <a href={watchUrl.href} target="_blank" rel="noopener" onClick={openYouTube}>Открыть в YouTube</a>
      </div>
    </div>
  );
}
