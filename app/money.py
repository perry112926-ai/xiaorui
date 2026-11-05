"""Amounts are integer cents; conversion is only for display."""

def format_cents(value: int) -> str:
    if type(value) is not int:
        raise TypeError('Amount must be integer cents')
    whole, fraction = divmod(abs(value), 100)
    return f'{"-" if value < 0 else ""}{whole}.{fraction:02d}'
