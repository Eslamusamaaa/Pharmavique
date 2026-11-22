// Microphone and speaker for the assistant and voice search. Audio stays on the device until it is
// sent for transcription; the server never stores it.
import {
  RecordingPresets,
  requestRecordingPermissionsAsync,
  setAudioModeAsync,
  useAudioPlayer,
  useAudioRecorder,
} from 'expo-audio';
import { useCallback, useState } from 'react';

import { speakLink, transcribeAudio } from '@/api/client';

export type MicState = 'idle' | 'listening' | 'transcribing';

/** Record a question, then turn it into text (Arabic, Saudi or Egyptian dialect). */
export function useVoiceInput() {
  const recorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);
  const [state, setState] = useState<MicState>('idle');
  const [error, setError] = useState<string | null>(null);

  const start = useCallback(async () => {
    setError(null);
    const permission = await requestRecordingPermissionsAsync();
    if (!permission.granted) {
      setError('نحتاج إذن المايك عشان نسمعك. فعّله من إعدادات الجوال.');
      return false;
    }
    await setAudioModeAsync({ allowsRecording: true, playsInSilentMode: true });
    await recorder.prepareToRecordAsync();
    recorder.record();
    setState('listening');
    return true;
  }, [recorder]);

  const stop = useCallback(async (): Promise<string | null> => {
    if (state !== 'listening') return null;
    await recorder.stop();
    await setAudioModeAsync({ allowsRecording: false, playsInSilentMode: true });
    const uri = recorder.uri;
    if (!uri) {
      setState('idle');
      setError('ما قدرنا نسجّل الصوت. جرّب مرة ثانية.');
      return null;
    }
    setState('transcribing');
    try {
      const { text } = await transcribeAudio(uri);
      setState('idle');
      if (!text.trim()) setError('ما سمعنا كلام واضح. جرّب تتكلم أقرب للجوال.');
      return text.trim() || null;
    } catch {
      setState('idle');
      setError('ما قدرنا نحوّل الصوت لنص الحين. جرّب مرة ثانية أو اكتب سؤالك.');
      return null;
    }
  }, [recorder, state]);

  return { state, error, start, stop };
}

/** Speak a text in the Saudi Arabic voice. */
export function useSpeaker() {
  const player = useAudioPlayer(null);
  const [loadingId, setLoadingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const speak = useCallback(
    async (id: string, text: string) => {
      setError(null);
      setLoadingId(id);
      try {
        const url = await speakLink(text);
        await setAudioModeAsync({ allowsRecording: false, playsInSilentMode: true });
        player.replace({ uri: url });
        player.play();
      } catch {
        setError('الصوت غير متاح الحين. جرّب بعد شوي.');
      } finally {
        setLoadingId(null);
      }
    },
    [player],
  );

  const stop = useCallback(() => player.pause(), [player]);

  return { speak, stop, loadingId, error, playing: player.playing };
}
