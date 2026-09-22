/**
 * Adapter: conversational assistant (RFP area 5).
 *
 * Mocked until task 6 builds POST /assistant/ask. The predefined questions ship
 * with cached answers so the demo is identical every time and survives the
 * provider being unreachable, which is what prompt 6 asks for.
 */
import { useMutation, useQuery } from '@tanstack/react-query';

import type { AssistantAnswer } from '@/api/contracts';
import { USE_MOCKS } from '@/mocks/config';
import { mockAssistantAsk, mockAssistantQuestions } from '@/mocks/assistant';

export interface PredefinedQuestion {
  question_id: string;
  question: string;
}

export function fetchAssistantQuestions(): Promise<PredefinedQuestion[]> {
  if (USE_MOCKS) return mockAssistantQuestions();
  throw new Error('GET /assistant/questions is not implemented yet (task 6).');
}

export function askAssistant(questionId: string): Promise<AssistantAnswer> {
  if (USE_MOCKS) return mockAssistantAsk(questionId);
  throw new Error('POST /assistant/ask is not implemented yet (task 6).');
}

export function useAssistantQuestions() {
  return useQuery({ queryKey: ['assistant-questions'], queryFn: fetchAssistantQuestions });
}

export function useAskAssistant() {
  return useMutation<AssistantAnswer, Error, string>({
    mutationFn: (questionId) => askAssistant(questionId),
  });
}
