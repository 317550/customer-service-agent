"""初始化本地演示订单。可重复运行，不会重复插入已有订单。"""

from app.config import DATABASE_PATH
from app.database import DuplicateOrderError, init_db, insert_order


DEMO_ORDERS = [
    {
        "order_id": "ORD001",
        "customer_id": "C001",
        "product": "机械键盘",
        "amount": 299.0,
        "status": "shipped",
    },
    {
        "order_id": "ORD002",
        "customer_id": "C002",
        "product": "无线鼠标",
        "amount": 159.0,
        "status": "paid",
    },
]


def main() -> None:
    init_db(DATABASE_PATH)
    inserted = 0
    for order in DEMO_ORDERS:
        try:
            insert_order(order, DATABASE_PATH)
            inserted += 1
        except DuplicateOrderError:
            # seed 脚本必须支持重复执行，已有演示订单无需报错。
            continue
    print(f"演示数据初始化完成：新增 {inserted} 条订单。")


if __name__ == "__main__":
    main()
