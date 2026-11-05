"""Render user-facing reason codes; semantic IDs and raw values are never translated."""
MESSAGES = {
    'vi': {
        'no_result': 'Chưa có kết quả cũ phù hợp. Hãy hỏi một câu đầy đủ.',
        'stale_reference': 'Kết quả đã chọn không còn phù hợp với phiên bản dữ liệu hiện tại. Hãy hỏi lại.',
        'stale_data': 'Dữ liệu đã thay đổi. Hãy hỏi lại để tính trên dữ liệu hiện tại.',
        'stale_catalog': 'Định nghĩa chỉ số đã thay đổi. Hãy hỏi lại.',
        'busy': 'Câu hỏi đang được xử lý. Vui lòng chờ hoặc dừng trước khi tiếp tục.',
        'not_tracked': 'Nguồn này không ghi nhận dữ liệu cần thiết để tính yêu cầu.',
        'field_not_tracked': 'Nguồn này không ghi nhận trường được yêu cầu: {fields}.',
        'source_scope': 'Hãy chọn một nguồn dữ liệu nằm trong phạm vi sản phẩm.',
        'source_conflict': 'Nguồn được chọn khác nguồn nêu trong câu hỏi. Hãy chọn nguồn để tiếp tục.',
        'memory_disabled': 'Thử nghiệm này đã tắt memory. Hãy hỏi câu đầy đủ.',
        'INTERRUPTED': 'Máy chủ đã khởi động lại trong khi xử lý. Bạn có thể thử lại.',
        'INTERNAL': 'Có lỗi xử lý nội bộ. Bạn có thể thử lại.',
        'TIMEOUT': 'Dịch vụ mô hình phản hồi quá lâu. Bạn có thể thử lại.',
        'RATE_LIMIT': 'Dịch vụ mô hình đang giới hạn lượt gọi. Vui lòng thử lại sau.',
        'GATEWAY_CHECK_FAILED': 'Không nhận được phản hồi đầy đủ từ gateway. Khoản dự phòng chi phí vẫn được giữ.',
        'QUEUE_FULL': 'Hệ thống đang đủ số lượt xử lý. Vui lòng thử lại sau.',
        'metric_unavailable': 'Chỉ số {metric} để trống ở nguồn không có đủ dữ liệu để tính.',
        'source_unavailable': 'Bỏ qua nguồn {source} vì không có đủ dữ liệu cần thiết.',
        'top_k': 'Kết quả gồm {count} nhóm đứng đầu; tổng chỉ tính trên các nhóm này.',
        'partial': 'Chỉ hiển thị {count} dòng đầu; không tính tổng trên kết quả chưa đầy đủ.',
        'empty': 'Không có dòng khớp điều kiện. Khoảng dữ liệu: {period}.',
        'small_sample': 'Có {count} dòng dựa trên ít hơn {minimum} người dùng hoặc sự kiện; cần thận trọng khi diễn giải.',
    }
}


def render(code, fallback, lang='en', params=None):
    if code == 'catalog_note' and (params or {}).get('localized', {}).get(lang):
        return params['localized'][lang]
    template = MESSAGES.get((lang or 'en').split('-')[0], {}).get(code)
    if not template:
        return fallback
    try:
        formatted = {k: ", ".join(map(str, v)) if isinstance(v, list) else v for k, v in (params or {}).items()}
        return template.format(**formatted)
    except KeyError:
        return fallback
