# Mini App

React и Vite, проверено с Node.js 24. Из корня проекта.

```sh
npm --prefix miniapp ci
npm --prefix miniapp run dev
```

Vite проксирует `/api` на локальный FastAPI по порту 4174. `?demo=sample` включает вымышленные записи, `?demo=empty` открывает пустой дневник. В деморежиме состояние находится в памяти вкладки. Обычный режим сохраняет сессии и дневник в SQLite через API.

`npm --prefix miniapp run build` собирает `miniapp/dist`, включая актуальный каталог NASS. [Локальный API и запуск](../docs/operations.md#локальный-запуск)
