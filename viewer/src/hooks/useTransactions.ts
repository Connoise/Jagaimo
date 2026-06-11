import { useQuery } from "@tanstack/react-query";
import { supabase } from "../lib/supabase";
import type { TransactionRow } from "../lib/types";

const LEDGER_LIMIT = 1000;

async function fetchTransactions(): Promise<TransactionRow[]> {
  const { data, error } = await supabase
    .from("transactions")
    .select("*")
    .order("trade_ts", { ascending: false })
    .order("txn_id", { ascending: false })
    .limit(LEDGER_LIMIT);
  if (error) throw error;
  return data as TransactionRow[];
}

/**
 * Trade ledger (read-only): rows are imported server-side from Vanguard CSV
 * exports and Coinbase fills. Newest LEDGER_LIMIT rows; filtering is client-side.
 */
export function useTransactions() {
  return useQuery({
    queryKey: ["transactions"],
    queryFn: fetchTransactions,
    refetchInterval: 60_000,
  });
}
