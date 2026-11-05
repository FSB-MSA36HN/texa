# Texa web

React + TypeScript + Vite. Scope sản phẩm và cách chuẩn bị API/DB ở [README gốc](../README.md); luồng UI/API ở [kiến trúc](../docs/ARCHITECTURE.md).

```sh
npm ci
npm run dev
npm run build
npm run lint
```

Vite dùng cổng `15173`, proxy `/api` tới API `18000`. `TEXA_WEB_PORT` và `TEXA_API_TARGET` cho phép cấu hình môi trường dev/test; cổng bị chiếm sẽ báo lỗi. Docker nginx giữ web và API cùng origin, tắt buffering SSE.

UI chọn Cosmetics hoặc Olist, mỗi query chỉ một nguồn. Trong shared demo, model do người tổ chức chọn, settings chỉ đọc và lịch sử tách theo cookie browser; localStorage không phải quyền truy cập dữ liệu. Nguồn không ghi nhận metric phải hiển thị lý do thay vì giả số liệu.

`npm run test:e2e` cần DB pilot riêng, Chromium và `TEXA_E2E_TEST_DSN=1`. Test tự chạy API scripted và Vite trên cổng riêng; không dùng provider thật. Chuẩn bị môi trường theo [CLASS_DEMO_CHECKS](../docs/CLASS_DEMO_CHECKS.md), không chạy fixture vào DB đang demo.
