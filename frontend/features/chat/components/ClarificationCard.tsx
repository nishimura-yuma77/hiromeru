"use client";

import { useState, type FormEvent } from "react";

import type { ClarificationAnswer, TurnItem } from "../types";
import styles from "../styles/Chat.module.scss";

type QuestionItem = Extract<TurnItem, { type: "clarification_request" }>;

type ClarificationCardProps = {
  item: QuestionItem;
  questionTurnId: number;
  previousAnswers?: ClarificationAnswer[];
  sending: boolean;
  maxMessageLength: number;
  onSubmit: (questionTurnId: number, questions: string[], answers: ClarificationAnswer[]) => Promise<void>;
};

const MAX_ANSWER_LENGTH = 1_000;
const timeFormatter = new Intl.DateTimeFormat("ja-JP", { hour: "2-digit", minute: "2-digit" });

export function ClarificationCard({ item, questionTurnId, previousAnswers, sending, maxMessageLength, onSubmit }: ClarificationCardProps) {
  const { questions, answered } = item.content;
  const [values, setValues] = useState(() => questions.map((_, index) =>
    previousAnswers?.find((answer) => answer.question_index === index)?.answer ?? ""
  ));
  const [errors, setErrors] = useState<Record<number, string>>({});
  const [generalError, setGeneralError] = useState<string | null>(null);

  function update(index: number, value: string) {
    setValues((current) => current.map((answer, position) => position === index ? value : answer));
    setErrors((current) => {
      const next = { ...current };
      delete next[index];
      return next;
    });
    setGeneralError(null);
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (sending || answered) return;

    const fieldErrors: Record<number, string> = {};
    const answers = questions.map((_, index) => {
      const answer = values[index].trim();
      if (!answer) fieldErrors[index] = "回答を入力してください。不明な場合は「まだ分からない」と入力できます。";
      else if (answer.length > MAX_ANSWER_LENGTH) fieldErrors[index] = "回答は1,000文字以内で入力してください。";
      return { question_index: index, answer };
    });
    setErrors(fieldErrors);
    if (Object.keys(fieldErrors).length > 0) {
      document.getElementById(`clarification-${item.item_id}-${Object.keys(fieldErrors)[0]}`)?.focus();
      return;
    }

    const contextText = questions.map((question, index) =>
      `質問${index + 1}: ${question}\n回答${index + 1}: ${answers[index].answer}`
    ).join("\n");
    if (contextText.length > maxMessageLength) {
      setGeneralError("質問と回答の合計が送信上限を超えています。回答を短くしてください。");
      return;
    }
    void onSubmit(questionTurnId, questions, answers);
  }

  return (
    <article className={styles.clarificationCard}>
      <header>
        <span className={styles.speaker}>Hiromeru AI</span>
        <h3>確認したいことがあります</h3>
        <p>分かる範囲で回答してください。分からない項目はそのまま教えていただけます。</p>
      </header>
      {answered ? (
        <>
          <ol className={styles.clarificationQuestions}>
            {questions.map((question, index) => <li key={index}>{question}</li>)}
          </ol>
          <p className={styles.clarificationAnswered} role="status">回答済み</p>
        </>
      ) : (
        <form onSubmit={submit} noValidate>
          {questions.map((question, index) => {
            const id = `clarification-${item.item_id}-${index}`;
            return (
              <div className={styles.clarificationField} key={id}>
                <label htmlFor={id}>{index + 1}. {question}</label>
                <textarea
                  aria-describedby={errors[index] ? `${id}-error` : undefined}
                  aria-invalid={Boolean(errors[index])}
                  disabled={sending}
                  id={id}
                  maxLength={MAX_ANSWER_LENGTH}
                  onChange={(event) => update(index, event.target.value)}
                  rows={3}
                  value={values[index]}
                />
                {errors[index] ? <small id={`${id}-error`} role="alert">{errors[index]}</small> : null}
              </div>
            );
          })}
          {generalError ? <p className={styles.clarificationError} role="alert">{generalError}</p> : null}
          <div className={styles.clarificationActions}>
            <button disabled={sending} type="submit">{sending ? "送信中…" : "回答をまとめて送信"}</button>
          </div>
        </form>
      )}
      <time dateTime={item.created_at}>{timeFormatter.format(new Date(item.created_at))}</time>
    </article>
  );
}
