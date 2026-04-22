import { useState, useEffect, useRef, useCallback } from "react";

/**
 * 语音输入 Hook - 基于浏览器 Web Speech API
 *
 * 用法:
 *   const { isSupported, isListening, transcript, startListening, stopListening } = useVoiceInput();
 *
 * 注意:
 * - 需要 Chrome/Edge 浏览器 + 联网 (Google 语音识别后端)
 * - Safari/Firefox 支持有限
 * - HTTPS 或 localhost 环境下可用
 */

interface SpeechRecognitionEvent {
  results: SpeechRecognitionResultList;
  resultIndex: number;
}

export function useVoiceInput() {
  const [isSupported, setIsSupported] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const [transcript, setTranscript] = useState("");
  const recognitionRef = useRef<any>(null);

  useEffect(() => {
    const SpeechRecognition =
      (window as any).SpeechRecognition ||
      (window as any).webkitSpeechRecognition;

    if (!SpeechRecognition) {
      setIsSupported(false);
      return;
    }

    setIsSupported(true);

    const recognition = new SpeechRecognition();
    recognition.lang = "zh-CN";
    recognition.continuous = true;       // 持续监听，直到手动 stop
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;

    // 累积所有已确认的结果 + 当前临时结果
    let confirmedText = "";

    recognition.onresult = (event: SpeechRecognitionEvent) => {
      let interim = "";
      confirmedText = "";
      for (let i = 0; i < event.results.length; i++) {
        const result = event.results[i];
        if (result.isFinal) {
          confirmedText += result[0].transcript;
        } else {
          interim += result[0].transcript;
        }
      }
      setTranscript(confirmedText + interim);
    };

    recognition.onerror = (event: any) => {
      console.warn("Speech recognition error:", event.error);
      setIsListening(false);
    };

    recognition.onend = () => {
      setIsListening(false);
    };

    recognitionRef.current = recognition;

    return () => {
      try {
        recognition.abort();
      } catch {}
    };
  }, []);

  const startListening = useCallback(() => {
    if (!recognitionRef.current || isListening) return;
    setTranscript("");
    try {
      recognitionRef.current.start();
      setIsListening(true);
    } catch (err) {
      console.warn("Failed to start speech recognition:", err);
    }
  }, [isListening]);

  const stopListening = useCallback(() => {
    if (!recognitionRef.current) return;
    try {
      recognitionRef.current.stop();
    } catch {}
  }, []);

  return {
    isSupported,
    isListening,
    transcript,
    startListening,
    stopListening,
  };
}
