# Bitget Telegram Bot — Starter v0.1

Bộ khung Python 3.12 cho Dương Tấn Minh. **Chỉ mô phỏng. Chưa phải bot AI giao dịch tiền thật.** Không cần và không nhận API key Bitget. Không có endpoint đặt lệnh lên sàn. `TRADING_MODE=live` khiến chương trình từ chối khởi động.

## 1. Chạy thử ngay, không cần mạng

Giải nén, mở terminal trong thư mục `Bitget_Telegram_Bot`:

```bash
python3 -m bot.demo
python3 -m unittest discover -s tests -v
```

Demo tạo một lệnh long giả lập, duyệt lệnh và mô phỏng chốt lời. Giá 100 trong demo chỉ là dữ liệu kiểm thử, không phải giá BTC. Không cần cài thư viện Python bên ngoài.

## 2. Cấu hình Telegram

1. Trên Telegram, mở tài khoản chính thức `@BotFather`, dùng `/newbot`, đặt tên và lấy bot token. Giữ token trên máy của bạn.
2. Nhắn `/start` cho bot vừa tạo để mở cuộc trò chuyện riêng.
3. Lấy Telegram user ID và private chat ID từ một bản cập nhật `getUpdates` của chính bot. Trong trò chuyện riêng, chat ID thường bằng user ID; dùng ID thực nhận được. Xem tài liệu chính thức bên dưới. Nếu đã cấu hình webhook cho bot này, gỡ webhook trước khi dùng long polling. Không chạy hai phiên bot cùng lúc.
4. Sao chép `.env.example` thành `.env`, điền `TELEGRAM_BOT_TOKEN`, `TELEGRAM_USER_ID`, `TELEGRAM_CHAT_ID`. Không commit hoặc gửi file `.env` lên chat/GitHub.

```bash
cp .env.example .env
# Chỉnh .env bằng trình soạn thảo của bạn

docker compose up -d --build
docker compose logs --tail=50 -f
```

Không có cổng HTTP nào cần mở. Volume `paper-data` giữ số dư, vị thế, tín hiệu, offset Telegram và nhật ký qua lần khởi động lại. `docker compose down` giữ volume; thêm `-v` sẽ xóa dữ liệu mô phỏng. Chỉ chạy một instance trên một volume.

Nếu không dùng Docker: export các biến trong `.env` qua cơ chế môi trường của terminal/IDE và đổi `DB_PATH` thành `paper.db` trong thư mục có quyền ghi. Chương trình không tự đọc `.env` khi chạy trực tiếp. Sau đó chạy `python3 -m bot.main`.

### Lấy ID mà không đưa token vào lịch sử lệnh

Dừng các phiên bot đang polling, gửi một tin nhắn mới cho bot trong **chat riêng**, rồi chạy đoạn sau. Token được nhập ẩn; đoạn mã chỉ in user ID và chat ID, không in nội dung tin nhắn. Không gửi token cho người khác.

```bash
python3 - <<'PY'
from getpass import getpass
from bot.main import request

token = getpass('Telegram bot token: ').strip()
try:
    base = 'https://api.telegram.org/bot' + token + '/'
    hook = request(base + 'getWebhookInfo', {})
    if not hook.get('ok'):
        print('Không xác thực được bot; kiểm tra token.')
    elif hook['result'].get('url'):
        print('Bot đang dùng webhook. Gỡ webhook trước khi dùng polling.')
    else:
        result = request(base + 'getUpdates', {'timeout': 0, 'allowed_updates': ['message', 'callback_query']})
        if not result.get('ok'):
            print('Không lấy được updates; kiểm tra token và phiên polling khác.')
        found = False
        for update in result.get('result', []):
            message = update.get('message', {})
            if message.get('chat', {}).get('type') == 'private':
                print('TELEGRAM_USER_ID=' + str(message['from']['id']))
                print('TELEGRAM_CHAT_ID=' + str(message['chat']['id']))
                found = True
        if result.get('ok') and not found:
            print('Chưa có tin nhắn riêng. Gửi tin nhắn mới cho bot rồi chạy lại.')
except Exception:
    print('Không kết nối được Telegram; kiểm tra mạng/token. Không chia sẻ token hoặc URL chứa token.')
PY
```

Điền các ID của chính bạn vào `.env` cùng token. Giữ nguyên `TRADING_MODE=paper` và `DB_PATH=/app/data/paper.db` nếu dùng Docker. Không cần API key Bitget. Nếu có nhiều người đã nhắn bot, chọn đúng cặp ID của mình.

Chạy trực tiếp với file `.env` do chính bạn chỉnh (đổi `DB_PATH=paper.db` trước):

```bash
set -a
source .env
set +a
python3 -m bot.main
```

Các lệnh `/help`, `/status`, `/nap`, `/von` không cần giá Bitget. `/demo long`, `/demo short`, duyệt lệnh và kiểm tra SL/TP cần mạng tới API giá công khai Bitget. Demo `python3 -m bot.demo` luôn chạy offline.

## 3. Thử luồng Telegram

```text
/help
/status
/nap 200
/von 250
/demo long
```

Số dư giả lập ban đầu là 100 USDT. `/nap 200` thêm 200 USDT GIẢ; `/von 250` phân bổ 250 USDT để tính lệnh. Bấm **Duyệt mô phỏng** trong 60 giây. Bot kiểm tra lại giá Bitget, tính lại khối lượng, rồi lưu vị thế mô phỏng. Dùng `/status` để xem kết quả. Có thể thử `/demo short` khi không còn vị thế.

`/demo` tạo tín hiệu kiểm thử thủ công với SL khoảng 1%, TP khoảng 2%. Đây không phải chiến lược đầu tư, không phải dự báo AI. Không có vòng tự tạo tín hiệu mỗi 15 phút ở phiên bản này.

| Lệnh | Ý nghĩa |
|---|---|
| `/nap 200` | Thêm số dư mô phỏng; không nạp tiền thật |
| `/rut 20` | Giảm số dư mô phỏng; không rút tiền thật |
| `/von 50` | Đổi ngân sách; không vượt tiền mô phỏng khả dụng |
| `/status`, `/pnl` | Xem trạng thái và PnL theo giá gần nhất |
| `/pause` | Ngừng tín hiệu mới, xóa tín hiệu chờ, tiếp tục kiểm tra SL/TP |
| `/resume` | Bỏ pause, không gỡ khóa lỗ ngày |
| `/demo long`, `/demo short` | Tạo tín hiệu kiểm thử trên giá Bitget |

Chưa có lệnh đóng khẩn cấp thủ công; cần triển khai bước tiếp theo trước live.

## 4. Quy tắc rủi ro đang có

- Rủi ro dự kiến mỗi lệnh: 0,5% số nhỏ hơn giữa ngân sách và equity mô phỏng.
- Qty = ngân sách lỗ / (khoảng cách entry–SL + dự phòng phí và trượt giá), có giới hạn giá trị vị thế ở mức 1x vốn. Làm tròn xuống 6 chữ số: chỉ là bước giả lập, chưa áp dụng thông số hợp đồng Bitget.
- Tối đa một vị thế. Chỉ Telegram user ID và chat ID đã cấu hình được thao tác.
- Tín hiệu hết hạn sau 60 giây; từ chối nếu giá lệch quá 0,1%, giá cũ hơn 10 giây hoặc thời gian giá nằm trong tương lai.
- Ngưỡng lỗ ngày: 15% equity tham chiếu đầu ngày; gồm PnL đã chốt, PnL đang mở và phí giả lập. Khi chạm ngưỡng, đóng vị thế mô phỏng và khóa mở mới.
- Chuyển ngày 00:00 Asia/Ho_Chi_Minh khi nhận tick hợp lệ; nếu bot tắt lúc nửa đêm, baseline lấy theo tick đầu tiên sau khi chạy lại, không thể tái tạo chính xác equity lúc nửa đêm.
- Đổi `/von` không thay baseline ngày và không gỡ khóa. Nạp/rút giả lập điều chỉnh cả cash và baseline cùng một lượng để không tính dòng tiền là lợi nhuận; thay đổi này cũng thay ngưỡng tiền tuyệt đối 15%. Khóa đã kích hoạt vẫn giữ đến ngày sau. Chỉ cho đổi vốn/nạp/rút khi không có vị thế.
- Giá polling dùng last trade, không phải mark price. SL/TP là kiểm tra cục bộ; không có bảo vệ khi bot tắt hoặc mất mạng. Giá nhảy có thể khiến lỗ vượt dự kiến.

Phí mỗi chiều giả định 0,06%, trượt giá mỗi chiều 0,05%; **không phải biểu phí Bitget**. Chưa tính funding, spread riêng, thanh lý, đòn bẩy thực tế hoặc hạn mức hợp đồng. Không dùng PnL này để kết luận chiến lược có lời. 15%/ngày là mức cấu hình người dùng yêu cầu, không phải mức rủi ro được khuyến nghị.

## 5. Cấu trúc

```text
bot/core.py          Logic tiền, vị thế, rủi ro và giao dịch SQLite
bot/main.py          Telegram polling + giá công khai Bitget
bot/demo.py          Demo offline
 tests/              Kiểm thử lõi và kiểm tra quyền Telegram
Dockerfile           Python không cần dependency ngoài
compose.yaml         Một dịch vụ, volume lưu trạng thái
.env.example         Mẫu cấu hình, không có bí mật
```

SQLite là lựa chọn starter để chạy ngay. Chưa có PostgreSQL, FastAPI, dashboard, Prometheus hay mô hình AI. Nhật ký audit nằm trong bảng `audit`; các phép đổi trạng thái nằm trong transaction SQLite để chống duyệt trùng và giữ dữ liệu qua restart.

## 6. Việc tiếp theo trước khi tiền thật

1. Thay SQLite bằng PostgreSQL với migration và khóa giao dịch khi cần nhiều worker.
2. Lưu nến 15 phút; chiến lược nền, backtest theo thời gian, phí/funding đúng và kiểm tra look-ahead bias.
3. Huấn luyện/đánh giá mô hình AI so với chiến lược nền; chưa đặt mục tiêu cam kết lợi nhuận.
4. Đọc số dư thật, xác định loại tài khoản Classic/UTA, bước qty, tick size, min order, margin mode và giới hạn thực từ Bitget. Không tự dùng toàn bộ tiền tài khoản cho bot.
5. Adapter đặt lệnh có client order ID, đối soát khớp một phần, xử lý timeout chưa rõ kết quả; SL/TP phía sàn được xác nhận, lệnh reduce-only, nút đóng khẩn cấp.
6. Dòng tiền thật phải được đối soát từ lịch sử chuyển tiền, daily baseline bền vững, đo PnL bằng mark price, theo dõi funding và quyền sở hữu vị thế.
7. Kiểm thử môi trường demo của sàn, mất mạng, restart, lệnh trùng, xác nhận cũ, sàn từ chối SL và ngưỡng lỗ. Chỉ sau đó mới cân nhắc live với vốn giới hạn.

## 7. Kiểm chứng và giới hạn

22 bài kiểm thử tự động: giới hạn khối lượng, duyệt trùng, tín hiệu hết hạn, giá cũ/lệch/tương lai/đảo thứ tự, SL/TP long/short, pause vẫn bảo vệ vị thế, khóa lỗ qua restart và đổi vốn, đổi ngày, số không hợp lệ, quyền Telegram, dòng tiền giả lập, lệnh trắng, callback sai định dạng, từ chối live và luồng Telegram offline với API giả lập.

Ngày 03/11/2026: đã build và khởi động Docker trên máy chạy, chạy thành công 22 kiểm thử trong image Python 3.12, kết nối Telegram bằng polling và nhận giá công khai Bitget. Trạng thái sau khởi động: paper, cash 100 USDT giả lập, chưa có vị thế. Phiên bản này không có outbox bảo đảm giao tin nhắn sau lỗi transport, không có bộ phát hiện toàn bộ tick bị bỏ lỡ khi offline. Không phải sản phẩm sẵn sàng giao dịch tiền thật.

Nếu gửi phản hồi Telegram lỗi sau khi lệnh đã đổi trạng thái nhưng trước khi lưu offset, update có thể được xử lý lại (ví dụ nạp/rút mô phỏng lặp). Kiểm tra `/status` sau lỗi kết nối; chưa có cơ chế exactly-once cho toàn bộ lệnh Telegram.

Tài liệu chính thức dùng để thiết kế adapter:
- https://www.bitget.com/docs/catalog/classic-contract-market/classic-contract-market
- https://core.telegram.org/bots/api#getupdates
- https://core.telegram.org/bots/api#answercallbackquery

## 8. Nghiên cứu mô hình BTCUSDT M15

Pipeline mới tách khỏi chương trình paper cơ bản. Không cần khóa Bitget. Dùng thư viện ML trong `requirements-ml.txt` (đã ghim các phiên bản trực tiếp); image nghiên cứu có Python 3.12 và libgomp. Chạy lại:

```bash
python3 -m research.data --days 365

docker build -f Dockerfile.research -t bitget-paper-research .
docker run --rm -v "$PWD:/app" bitget-paper-research python -m unittest discover -s tests -v
docker run --rm -v "$PWD:/app" bitget-paper-research python -m research.train
docker run --rm -v "$PWD:/app" bitget-paper-research python -m research.predict
```

Lệnh thu thập lưu `data/BTCUSDT_15m.csv` và manifest cùng tên có hậu tố `.json`. Kiểm tra nến đóng, trùng, số hữu hạn, OHLC, đủ khoảng lịch sử và thiếu nến; từ chối âm thầm huấn luyện trên lịch sử không liên tục. File tải dở được giữ, lần chạy lại ghép và kiểm tra. Mỗi lần chạy vẫn phân trang toàn khoảng yêu cầu để kiểm tra đầy đủ.

Đặc trưng: lợi suất 1/4/16/96 nến, ATR14, biên độ/thân nến, khối lượng tương đối, độ biến động, chênh lệch EMA12/48 với cửa sổ hữu hạn 96 nến, độ dốc và xu hướng H1 so với SMA24 giờ. Nến H1 chỉ có sau khi cả 4 nến M15 đã đóng; tính đặc trưng online giống offline. Nhãn là lợi suất từ open nến kế tiếp đến close nến thứ tư, với vùng trung tính `max(0.27%, 0.5 ATR/close)`. Đây là giả thuyết nghiên cứu đầu tiên, không phải thông số đã tối ưu.

Ba ứng viên: quy tắc EMA cùng chiều H1, Logistic Regression và LightGBM. ML dùng ngưỡng điểm cố định 0.55, chưa hiệu chỉnh xác suất. Chia 80% đầu làm phát triển, 20% cuối làm holdout; ba fold walk-forward mở rộng, gap 4 nến loại nhãn chồng ranh giới. Scaler chỉ fit trên train. Chọn ứng viên bằng lợi nhuận trung bình các fold, không chọn lại bằng holdout.

Backtest dùng paper Engine với vốn đầu 100, rủi ro 0.5%/lệnh, giới hạn 1x và khóa lỗ ngày 15%. Vào open nến sau tín hiệu, SL `max(1.5 ATR, 0.3% entry)`, TP gấp hai khoảng SL, giữ tối đa 4 nến. Nếu một nến chạm cả SL và TP, tính SL trước; gap mở cửa thoát ở giá open. Gồm phí 0.06% và trượt giá 0.05% mỗi chiều; thêm kiểm tra chi phí gấp đôi. Chưa tính funding, thanh khoản, độ trễ duyệt và đường đi giá thực trong nến. Báo cáo drawdown dựa trên equity ở cuối nến, không phải toàn bộ biến động intrabar.

Đầu ra:

- `artifacts/report.md`, `report.json`: kết quả, giả định và hash dữ liệu.
- `artifacts/evaluated.joblib`: snapshot được dùng đánh giá holdout.
- `artifacts/model.joblib`: snapshot fit lại toàn bộ nhãn đã biết để quan sát tương lai.

Chỉ load artifact do chính pipeline này tạo; joblib không phù hợp với file tải từ nguồn không tin cậy. Dữ liệu và artifact không được commit. Không diễn giải accuracy thành khả năng có lợi nhuận; lớp trung tính có thể chiếm phần lớn dữ liệu.

Cổng cho đề xuất paper yêu cầu: trung bình CV dương, ít nhất 2/3 fold dương, holdout ít nhất 30 lệnh, lợi nhuận dương cả chi phí thường và gấp đôi, drawdown holdout dưới 10%. Chưa đạt thì **observe_only**, không có nút duyệt lệnh mô hình. Đây là tiêu chí sàng lọc paper, không phải tiêu chí đủ cho live. Nếu tiếp tục thử thông số sau khi đã xem holdout, phải coi holdout cũ là dữ liệu phát triển và dùng giai đoạn mới để đánh giá.

Bật tích hợp trên cùng dịch vụ/volume paper, chỉ chạy một phiên polling:

```bash
docker compose -f compose.yaml -f compose.ml.yaml up -d --build
docker compose -f compose.yaml -f compose.ml.yaml logs --tail=50 -f
```

- `/model`: kết quả đánh giá và trạng thái cổng paper.
- `/predict`: dự báo theo nến M15 đã đóng gần nhất.
- Bot quan sát một lần mỗi nến đóng, lưu audit `model_forecast`; không phát bù tín hiệu lịch sử. Tín hiệu tự động dừng khi `/pause`.
- Nếu mô hình đạt cổng, chỉ đề xuất trong phút đầu sau nến đóng; vẫn phải duyệt Telegram trong 60 giây. SL/TP theo ATR; thời hạn giữ vị thế lưu bền vững và vẫn được kiểm tra khi pause/restart. Quá hạn khi mất mạng sẽ đóng ở tick hợp lệ tiếp theo.
- Model quá 14 ngày hoặc thiếu nến mới nhất: không dự báo/tạo đề xuất; cần thu thập và huấn luyện lại, sau đó restart dịch vụ để load artifact mới.
- `/demo long` và `/demo short` vẫn là kiểm thử thủ công, độc lập với kết quả ML.

Kết quả lần chạy đầu ngày 03/11/2026: 35.040 nến liên tục/365 ngày; LightGBM được chọn nhưng **observe_only** vì chỉ có 1 lệnh ở toàn bộ ba fold và 0 lệnh ở holdout. Chưa chứng minh được lợi thế giao dịch. Xem `artifacts/report.md` để đọc số liệu đầy đủ.

Đã chạy thành công 37 kiểm thử trên image triển khai Python 3.12, gồm đặc trưng nhân quả và đồng nhất online/offline, phân trang không mất nến, mô phỏng SL trước TP khi cùng chạm, phí, thời hạn vị thế qua restart/pause, không tạo đề xuất từ mô hình observe_only và yêu cầu duyệt trước khi mở paper. Bot triển khai đã lưu dự báo M15 vào audit; dữ liệu paper trước cập nhật được giữ nguyên.

Tài liệu tham khảo triển khai: [TimeSeriesSplit và gap](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html), [LightGBM Python](https://lightgbm.readthedocs.io/en/stable/Python-Intro.html).

## 9. V2 — dự đoán kết quả giao dịch và kiểm chứng tương lai

V2 nằm riêng trong `artifacts/v2`; không thay model Telegram V1 hoặc ví paper. Mục tiêu học là **lệnh có lời ròng sau SL/TP hoặc timeout**, thay vì nhãn tăng/giảm/trung tính. Dataset vẫn lưu cờ TP trước SL để kiểm tra. Hai mô hình Logistic/Ridge và LightGBM dự đoán xác suất lời và lợi suất ròng dự kiến cho cả long và short; xác suất được hiệu chỉnh bằng sigmoid trên đoạn calibration nằm sau train. Bộ lọc cố định yêu cầu xác suất lời >=55% và lợi suất ròng dự kiến >=0.03%; không hạ ngưỡng theo kết quả đoạn cuối.

Nguồn dữ liệu: 84 ngày có đủ nến M1 và funding (API funding trả khoảng 90 ngày). Đã tải 120.960 nến M1, đối chiếu OHLC tổng hợp với M15 và tạo 15.042 ví dụ long/short có thể thực hiện. Cả nhãn và replay bao gồm độ trễ duyệt 1 phút, từ chối giá lệch >0.1%, phí/slippage, SL trước TP nếu cùng chạm trong một phút, funding thực với close M1 đại diện mark price. Funding tại đúng thời điểm vào không tính; vị thế giữ đến thời điểm funding/expiry tính funding một lần. Các giả định này chưa mô phỏng thanh khoản hay đường đi giá trong một phút.

```bash
python3 -m research.microdata --days 84
python3 -m research.funding

docker run --rm -v "$PWD:/app" bitget-paper-research python -m research.improve
docker run --rm -v "$PWD:/app" bitget-paper-research python -m research.improve --horizon 240
```

`artifacts/v2/report.md` là nghiên cứu giữ tối đa 1 giờ; `artifacts/v2_240/report.md` là cấu hình giữ tối đa 4 giờ, đều lấy tín hiệu M15. Hai cửa sổ đầu dùng chọn ứng viên; cửa sổ cuối dùng chẩn đoán. Toàn bộ giai đoạn đã được xem trong nghiên cứu trước, nên các số liệu này được ghi rõ là **thăm dò lịch sử**, không gọi là holdout hoàn toàn mới. Không so trực tiếp accuracy V1 và V2 vì nhãn và khoảng dữ liệu khác nhau. Chỉ số Brier so với dự báo tỷ lệ lời cố định từ calibration giúp kiểm tra chất lượng xác suất, không chứng minh lợi thế giao dịch.

Kết quả: cấu hình 1 giờ không có giao dịch đạt điều kiện; cấu hình 4 giờ có 1 giao dịch thắng ở cửa sổ chọn ứng viên và 0 giao dịch ở đoạn chẩn đoán cuối. Chưa đủ bằng chứng cải thiện tỷ lệ thắng. Tất cả artifact V2 luôn giữ `paper_proposals_enabled=false`; không có tự động nâng cấp sang đặt lệnh.

Dịch vụ quan sát tương lai độc lập:

```bash
docker compose -f compose.research.yaml up -d --build
docker compose -f compose.research.yaml logs --tail=20
```

Dịch vụ không nhận token Telegram/Bitget và không mount volume ví paper. Nó ghi dự báo trong phút đầu sau mỗi nến M15 đóng, chỉ cho nến nằm sau giai đoạn nghiên cứu, không ghi lùi dự báo sau khi đã thấy diễn biến giá. Lưu cả hai hướng như mẫu đối chứng và tối đa một hướng đạt bộ lọc. Sau 1 giờ, chấm lời/lỗ bằng M1 và funding rồi lưu vào `data/shadow/forward.db`. Những mẫu này chồng lấn thời gian, là kết quả giả định trên một đơn vị vị thế, **không phải PnL của danh mục giao dịch**. Thống kê tách theo hash model để không gộp các phiên bản.

Model quá 14 ngày sẽ ngừng ghi dự báo mới; cần huấn luyện lại, lưu thành phiên bản mới và restart dịch vụ. Bot Telegram `/model`, `/predict` vẫn là V1; V2 đang quan sát riêng. Muốn xem số mẫu mới:

```bash
docker compose -f compose.research.yaml exec -T shadow python -c 'from research.shadow import Shadow; print(Shadow("/app/artifacts/v2", "/app/shadow/forward.db").summary())'
```

Việc tiếp theo để cải thiện giao dịch thực chất là đánh giá các dự báo tương lai đã đóng băng trước khi biết kết quả. Nếu tiếp tục thay dữ liệu/đặc trưng/SL/TP hoặc ngưỡng thì giữ riêng hash và đánh giá phiên bản mới; không cộng kết quả nghiên cứu lịch sử vào tỷ lệ thắng tương lai.

## 10. Theo dõi forward test V2 bằng Telegram

Bot cấu hình bằng `compose.yaml` + `compose.ml.yaml` hiện đọc ledger V2 qua mount **chỉ đọc**. Dịch vụ V2 ghi dữ liệu và tạo event thông báo trong cùng transaction SQLite; bot Telegram đọc event rồi lưu cursor sau khi gửi thành công. Mất mạng sẽ thử gửi lại; timeout sau khi Telegram đã nhận có thể gây thông báo trùng, không tạo giao dịch.

```bash
docker compose -f compose.research.yaml up -d --build
docker compose -f compose.yaml -f compose.ml.yaml up -d --build
```

Lệnh trên Telegram:

- `/forward`: heartbeat, số mẫu, số đã chấm/bị loại, tỷ lệ lời ròng và lợi suất trung bình; tách toàn bộ đối chứng với tín hiệu đạt bộ lọc.
- `/predict2`: dự báo V2 gần nhất đã được ghi trước diễn biến giá, gồm xác suất lời, giá tham chiếu, SL/TP và thời hạn. Không tính lại dự báo cũ bằng giá mới.
- `/results`: tối đa 4 kết quả gần nhất của phiên bản model đang chạy. Mẫu bị loại vì lệch giá không tính là thua.
- `/model2`: mục tiêu mô hình V2 và giới hạn đánh giá.
- `/pause`: ngừng thông báo tự động; V2 vẫn thu thập/chấm dữ liệu để không làm lệch mẫu. Các thông báo trong lúc pause được bỏ qua; vẫn xem lại bằng `/predict2`, `/results`, `/forward`. `/resume` bật lại thông báo mới.

Thông báo tự động gồm một cặp dự báo long/short cho mỗi nến đóng và kết quả từng hướng khi hết thời hạn đánh giá. Không có nút duyệt hay mở vị thế từ thông báo V2. Khi `FORWARD_DB` được cấu hình, thông báo tự động V1 được tắt để tránh nhầm; `/model`, `/predict` vẫn truy vấn V1 thủ công.

Đọc tỷ lệ có lời ròng cùng số mẫu và chi phí. Số mẫu đã ghi chưa phải số giao dịch thật; mẫu long/short đối chứng và các kỳ liên tiếp có thể chồng lấn. Không cộng dồn lợi suất các mẫu thành lợi nhuận danh mục hoặc drawdown. Chưa có mẫu đã chấm thì hiển thị “chưa đủ mẫu”, không báo tỷ lệ thắng 0%.

Ngày 03/11/2026: đã xác nhận cặp dự báo thật đầu tiên ghi lúc **22:15:07 Asia/Ho_Chi_Minh**, trước thời điểm vào giả định 22:16; cả hai hướng không đạt bộ lọc. Thời hạn đánh giá là 23:15, chấm khi có đủ M1 và funding. Thông tin này không phải bằng chứng tỷ lệ thắng; chỉ xác nhận pipeline đã ghi dự báo trước kết quả.

Đã kiểm chứng 74 kiểm thử trên image bot triển khai, đọc SQLite qua mount chỉ đọc, cursor thông báo tiến sau khi gửi thành công và gửi bảng `/forward` thật tới chat Telegram đã cấu hình. Tại thời điểm xác minh đầu tiên: 2 mẫu đối chứng, 0 mẫu đã chấm, 0 tín hiệu đạt bộ lọc; chưa có tỷ lệ thắng thực tế để công bố.

### Một phương án duy nhất: hướng, đòn bẩy, SL/TP

Thông báo V2 và `/predict2` hiện chỉ hiển thị **một hướng ưu tiên**. Nếu có hướng đạt bộ lọc, ưu tiên hướng đó; nếu chưa có, chọn lợi suất ròng dự kiến cao hơn, rồi xác suất lời cao hơn khi hòa. Hòa hoàn toàn dùng thứ tự tên hướng cố định, không xem kết quả tương lai. Đây là thay đổi cách trình bày/chấm hướng ưu tiên, không phải huấn luyện một mô hình có tỷ lệ thắng mới.

Đòn bẩy hiển thị **1x cố định**, không phải đòn bẩy tối ưu do mô hình học được. SL cách giá tham chiếu `max(1.5 ATR14, 0.3% giá)`, TP gấp hai khoảng SL; short đảo chiều so với long. Giá tham chiếu là giá của nến tín hiệu đã đóng, không phải báo giá vào hiện tại. Nếu không đạt bộ lọc, vẫn ghi rõ hướng ưu tiên chỉ để kiểm chứng và không tạo lệnh.

`/results` và thông báo kết quả tự động chỉ đưa hướng ưu tiên của từng nến. `/forward` thêm nhóm “Hướng ưu tiên” để đo tỷ lệ có lời của đúng một lựa chọn mỗi nến; giữ riêng nhóm đạt bộ lọc và cả hai hướng đối chứng. Worker vẫn lưu cả hai hướng gốc; không thay điểm dự báo hoặc kết quả đã ghi. Các hướng liên tiếp vẫn có thể chồng lấn thời gian, không phải PnL danh mục.

## 11. V3 — thử nghiệm các chỉ báo thông dụng

Đã bổ sung **RSI14, MACD12/26/9, Bollinger Bands20/2, ADX14 và DI+/DI-, Stochastic14/3/3, OBV, rolling VWAP20, MFI14** bằng TA-Lib 0.6.8. Cùng 14 đặc trưng nền và các tương tác theo hướng long/short, V3 dùng 42 đầu vào. Đây vẫn là các biến đổi của giá và khối lượng, không phải nguồn dữ liệu độc lập như sổ lệnh/tin tức.

Mỗi chỉ báo được tính bằng TA-Lib trên đúng 200 nến đã đóng tại thời điểm dự báo; không tính từ nến đang chạy. Phần khởi tạo EMA/Wilder được giới hạn lại trong cửa sổ này để huấn luyện và online giống nhau, nên có thể lệch nhỏ với biểu đồ sử dụng lịch sử khởi tạo dài hơn. Bộ thu thập online V3 lấy 300 nến để còn ít nhất 200 nến đóng sau khi loại nến đang chạy. OBV dùng thay đổi 20 nến chuẩn hóa theo khối lượng; VWAP là rolling 20 nến, không phải VWAP neo phiên.

So sánh công bằng chỉ đổi đặc trưng: cùng mẫu/nhãn, tham số LightGBM, calibration theo thời gian, SL/TP, độ trễ và chi phí. Báo cáo ở `artifacts/v3/report.md`, chi tiết giao dịch từng fold trong các CSV cùng thư mục. Các kết quả lịch sử vẫn là thăm dò.

Kết quả đoạn chẩn đoán cuối khi ép chọn một hướng mỗi nến và replay một vị thế:

| Bộ đặc trưng | Lệnh | Tỷ lệ lời sau chi phí | Lợi nhuận giả lập |
|---|---:|---:|---:|
| Nền V2 | 538 | 19.70% | -60.57% |
| Thêm chỉ báo V3 | 540 | 18.33% | -61.73% |

Không có lệnh nào đạt bộ lọc xác suất/edge ở cả hai nhánh. Vì chưa cải thiện, **V2 vẫn là mô hình mặc định**, V3 chỉ chạy thử song song. Đòn bẩy 1x, các ngưỡng và quy tắc SL/TP không đổi; không bật giao dịch tiền thật.

```bash
docker build -f Dockerfile.research -t bitget-paper-indicators .
docker run --rm -v "$PWD:/app" bitget-paper-indicators python -m research.indicator_study
docker compose -f compose.research.yaml up -d --build shadow-indicators
docker compose -f compose.yaml -f compose.ml.yaml up -d --build
```

V3 ghi tương lai riêng tại `data/shadow/forward_v3.db`, không trộn thống kê V2. `/indicators` trên Telegram xem thử nghiệm V3 với một hướng ưu tiên, SL/TP, RSI/ADX/MACD tại lúc dự báo; nếu chưa đến cửa sổ nến mới sẽ báo đang chờ, không ghi lùi dự báo. `/predict2` và thông báo tự động vẫn dùng V2; không gửi thêm một luồng thông báo V3 để tránh nhầm hai hướng.

88 kiểm thử đã đạt, gồm đối chiếu TA-Lib/công thức Bollinger-VWAP, chỉ báo không nhìn tương lai, khớp online/offline trên cửa sổ 200 nến, giá/khối lượng không đổi không tạo vô cực, schema model cũ vẫn tương thích và lưu snapshot chỉ báo để không tính lại theo giá mới.

Nguồn công thức/thư viện: [TA-Lib momentum](https://ta-lib.github.io/ta-lib-python/func_groups/momentum_indicators.html), [Bollinger Bands](https://ta-lib.github.io/ta-lib-python/func_groups/overlap_studies.html), [TA-Lib 0.6.8](https://pypi.org/project/TA-Lib/0.6.8/).
