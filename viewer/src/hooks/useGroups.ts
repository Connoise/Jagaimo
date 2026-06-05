import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { supabase } from "../lib/supabase";
import type { GroupMember, InstrumentGroup } from "../lib/types";

export interface GroupWithMembers extends InstrumentGroup {
  members: GroupMember[];
}

async function fetchGroups(): Promise<GroupWithMembers[]> {
  const [groupsRes, membersRes] = await Promise.all([
    supabase.from("instrument_groups").select("*").order("name"),
    supabase.from("group_members").select("*"),
  ]);
  if (groupsRes.error) throw groupsRes.error;
  if (membersRes.error) throw membersRes.error;
  const members = membersRes.data as GroupMember[];
  return (groupsRes.data as InstrumentGroup[]).map((g) => ({
    ...g,
    members: members.filter((m) => m.group_id === g.group_id),
  }));
}

export function useGroups() {
  const qc = useQueryClient();
  const query = useQuery({ queryKey: ["groups"], queryFn: fetchGroups });
  const invalidate = () => qc.invalidateQueries({ queryKey: ["groups"] });

  const createGroup = useMutation({
    mutationFn: async (name: string) => {
      const { error } = await supabase.from("instrument_groups").insert({ name });
      if (error) throw error;
    },
    onSuccess: invalidate,
  });

  const deleteGroup = useMutation({
    mutationFn: async (group_id: number) => {
      const { error } = await supabase
        .from("instrument_groups")
        .delete()
        .eq("group_id", group_id);
      if (error) throw error;
    },
    onSuccess: invalidate,
  });

  const addMember = useMutation({
    mutationFn: async (args: {
      group_id: number;
      instrument_id: number;
      weight?: number;
    }) => {
      const { error } = await supabase.from("group_members").upsert({
        group_id: args.group_id,
        instrument_id: args.instrument_id,
        weight: args.weight ?? 1.0,
      });
      if (error) throw error;
    },
    onSuccess: invalidate,
  });

  const removeMember = useMutation({
    mutationFn: async (args: { group_id: number; instrument_id: number }) => {
      const { error } = await supabase
        .from("group_members")
        .delete()
        .eq("group_id", args.group_id)
        .eq("instrument_id", args.instrument_id);
      if (error) throw error;
    },
    onSuccess: invalidate,
  });

  return { ...query, createGroup, deleteGroup, addMember, removeMember };
}
