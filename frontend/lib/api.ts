const BASE_URL = process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8000'

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`API ${res.status}: ${text || res.statusText}`)
  }
  return res.json() as Promise<T>
}

export async function generateLineart(imageUrl: string, mode: 'canny' | 'fine' = 'fine'): Promise<string> {
  const { lineart_b64 } = await post<{ lineart_b64: string }>('/artworks/lineart', { image_url: imageUrl, mode })
  return `data:image/png;base64,${lineart_b64}`
}

export const api = { post }
