// 파일 업로드·단건 조회 공용 API(대화 첨부 · 자료함).
import { api, failure, networkError, requestHeaders } from '../api';

export const MAX_FILES = 10;
export const MAX_FILE_BYTES = 50 * 1024 * 1024;

export interface UploadItem {
  file_id: number;
  name: string;
  kind: string;
  status: string;
  reason: string | null;
}

export interface FileOut {
  file_id: number;
  name: string;
  ext: string;
  kind: string;
  size: number;
  status: string;
  reason: string | null;
  uploaded_by: number;
  uploaded_at: string;
  pages: number | null;
  summary: string;
  deleted: boolean;
  axes: Record<string, string[]>;
}

/** POST /api/files (multipart `files` 반복). 업로드에는 chat_id 를 주지 않고 메시지 전송 때 file_ids 로 잇는다. */
export async function uploadFiles(files: File[], signal?: AbortSignal): Promise<UploadItem[]> {
  const form = new FormData();
  for (const f of files) form.append('files', f, f.name);
  const { headers, token } = requestHeaders({}, true);
  let res: Response;
  try {
    res = await fetch('/api/files', { method: 'POST', headers, body: form, signal });
  } catch (e) {
    if (signal?.aborted) throw e;
    throw networkError();
  }
  if (!res.ok) throw await failure(res, token);
  const data = (await res.json()) as { items?: UploadItem[] };
  return data.items ?? [];
}

export const getFile = (fileId: number, signal?: AbortSignal) => api<FileOut>(`/api/files/${fileId}`, { signal });
