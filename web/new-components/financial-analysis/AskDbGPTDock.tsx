import { ArrowRightOutlined, CloseOutlined, InfoCircleOutlined, SendOutlined } from '@ant-design/icons';
import { Button, Input, Tooltip } from 'antd';
import React, { useState } from 'react';
import { useReportData } from './ReportDataContext';
import styles from './financial-analysis.module.css';
import { MockAnswer, OpenEvidence } from './types';
interface AskDbGPTDockProps {
  onOpenEvidence: OpenEvidence;
}
const AskDbGPTDock: React.FC<AskDbGPTDockProps> = ({ onOpenEvidence }) => {
  const { data } = useReportData();
  const questions = data.mode === 'demo' ? data.demoQuestions || [] : [];
  const [query, setQuery] = useState('');
  const [answer, setAnswer] = useState<MockAnswer | null>(null);
  const submit = (question?: string) => {
    const value = (question || query).trim();
    if (!value) return;
    const matched =
      questions.find(item => item.question === value) ||
      [...questions]
        .sort((a, b) => a.priority - b.priority)
        .find(item => item.keywords.some(keyword => value.includes(keyword)));
    setQuery(value);
    setAnswer(
      matched
        ? { ...matched, question: value }
        : {
            question: value,
            answer:
              data.mode === 'demo'
                ? '当前示例暂未覆盖这个问题。可以从研究发现继续查看依据。'
                : '当前报告尚未接入追问服务，请先通过指标和来源核对数据。',
            findingId: '',
          },
    );
  };
  return (
    <section className={styles.composer} aria-label='Ask DB-GPT'>
      <div className={styles.suggestions}>
        {questions.slice(0, 3).map(item => (
          <button type='button' key={item.question} onClick={() => submit(item.question)}>
            {item.label}
          </button>
        ))}
      </div>
      <Input
        value={query}
        onChange={event => setQuery(event.target.value)}
        onPressEnter={event => {
          if (!event.nativeEvent.isComposing) submit();
        }}
        placeholder='Ask DB-GPT about this report…'
        aria-label='向 DB-GPT 追问报告'
        className={styles.composerInput}
        suffix={
          <Button
            type='primary'
            size='small'
            icon={<SendOutlined />}
            onClick={() => submit()}
            disabled={!query.trim()}
            aria-label='发送问题'
          />
        }
      />
      {answer && (
        <div className={styles.answer} role='status'>
          <div className={styles.answerHeading}>
            <span>
              DB-GPT{' '}
              <Tooltip title={data.mode === 'demo' ? '本地示例回答，未调用模型。' : '当前报告尚未接入追问服务。'}>
                <InfoCircleOutlined />
              </Tooltip>
            </span>
            <button type='button' aria-label='收起回答' onClick={() => setAnswer(null)}>
              <CloseOutlined />
            </button>
          </div>
          <p>{answer.answer}</p>
          {answer.findingId && (
            <button
              type='button'
              className={styles.textLink}
              onClick={() => onOpenEvidence({ findingId: answer.findingId })}
            >
              查看回答依据 <ArrowRightOutlined />
            </button>
          )}
        </div>
      )}
    </section>
  );
};
export default AskDbGPTDock;
