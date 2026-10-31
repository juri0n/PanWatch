"""Field errors for the manual spot form; no credentials or execution parameters."""
from .adapter import number
from .contracts import Instrument


class ConfigFieldError(ValueError):
    def __init__(self, code, field, message):
        super().__init__(message)
        self.code, self.field = code, field


def validate_position_fields(exchange, positions):
    for index, position in enumerate(positions):
        if not isinstance(position, dict) or set(position) != {"symbol", "quantity"}:
            raise ConfigFieldError("crypto_position_fields", f"positions.{index}", "持仓只接受交易对和数量两个字段。")
        try:
            Instrument(exchange, position["symbol"])
        except (ValueError, TypeError):
            raise ConfigFieldError("crypto_pair", f"positions.{index}.symbol", f"第 {index + 1} 项交易对格式有误，请填写 BTC/USDT 这样的 USD/USDT 现货交易对。") from None
        try:
            if not isinstance(position["quantity"], str):
                raise ValueError()
            number(position["quantity"])
        except (ValueError, TypeError):
            raise ConfigFieldError("crypto_quantity", f"positions.{index}.quantity", f"第 {index + 1} 项持仓数量应为非负数字（例如 0.001），不能填写 USDT 等币种名称；最多32位有效数字，非零值范围为 1e-24 到 1e21 以下。") from None


def validate_threshold_price(rule, index):
    try:
        if not isinstance(rule["price"], str):
            raise ValueError()
        number(rule["price"], positive=True)
    except (ValueError, TypeError):
        raise ConfigFieldError("crypto_threshold_price", f"alerts.{index}.price", f"第 {index + 1} 项阈值价格应为大于零的有效数字，单位为交易对的报价币种。") from None
