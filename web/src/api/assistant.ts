/**
 * Adapter: conversational assistant (RFP area 5). Real, as of task 6.
 *
 * The backend turns a free-text question into a validated query spec, runs
 * it, and returns a paragraph whose every number was checked against the
 * rows. Starter questions answer from the backend's shipped response cache,
 * so the demo works with no model key and no network.
 */
import { useMutation, useQuery } from '@tanstack/react-query';

import type { AssistantAnswer, StarterQuestion } from '@/api/client';
import { api } from '@/api/client';

export function fetchStarterQuestions(): Promise<StarterQuestion[]> {
  return api.assistantQuestions().then((page) => page.items);
}

export function askAssistant(question: string): Promise<AssistantAnswer> {
  return api.ask(question);
}

export function useStarterQuestions() {
  return useQuery({
    queryKey: ['assistant-questions'],
    queryFn: fetchStarterQuestions,
    staleTime: Infinity,
  });
}

export function useAskAssistant() {
  return useMutation<AssistantAnswer, Error, string>({ mutationFn: askAssistant });
}
