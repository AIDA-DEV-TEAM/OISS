/**
 * Adapter: export service (RFP area 8).
 *
 * Mocked until task 5 builds POST /export, GET /export/{id} and GET /exports.
 * The context an export carries is modelled here exactly as task 5 specifies,
 * because that context is the part a reviewer checks six months later.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import type { ExportContext, ExportFormat, ExportRecord, ExportType } from '@/api/contracts';
import { USE_MOCKS } from '@/mocks/config';
import { mockCreateExport, mockRecentExports } from '@/mocks/exports';

export interface CreateExportInput {
  export_type: ExportType;
  format: ExportFormat;
  context: ExportContext;
}

export function fetchRecentExports(): Promise<ExportRecord[]> {
  if (USE_MOCKS) return mockRecentExports();
  throw new Error('GET /exports is not implemented yet (task 5).');
}

export function createExport(input: CreateExportInput): Promise<ExportRecord> {
  if (USE_MOCKS) return mockCreateExport(input);
  throw new Error('POST /export is not implemented yet (task 5).');
}

export function useRecentExports() {
  return useQuery({ queryKey: ['exports'], queryFn: fetchRecentExports });
}

export function useCreateExport() {
  const client = useQueryClient();
  return useMutation<ExportRecord, Error, CreateExportInput>({
    mutationFn: createExport,
    onSuccess: () => {
      // A completed export belongs at the top of the Exports screen.
      void client.invalidateQueries({ queryKey: ['exports'] });
    },
  });
}
