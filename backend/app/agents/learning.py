from ..db.database import query_all


def get_weights(account_id: int) -> list[dict]:
    rows = query_all(
        "SELECT rule_key, weight, trades_count, win_rate, avg_pnl FROM learning_weights WHERE account_id = ?",
        (account_id,),
    )
    return [dict(r) for r in rows]
