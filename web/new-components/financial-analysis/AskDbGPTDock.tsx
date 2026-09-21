import { ArrowRightOutlined, CloseOutlined, InfoCircleOutlined, SendOutlined } from '@ant-design/icons';
import { Button, Input, Tooltip } from 'antd';
import React, { useState } from 'react';
import styles from './financial-analysis.module.css';
import { mockAnswers } from './mock-data';
import { MockAnswer } from './types';
interface AskDbGPTDockProps {
  onOpenEvidence: (findingId: string) => void;
}
const AskDbGPTDock: React.FC<AskDbGPTDockProps> = ({ onOpenEvidence }) => {
  const [query, setQuery] = useState('');
  const [answer, setAnswer] = useState<MockAnswer | null>(null);
  const submit = (question?: string) => {
    const value = (question || query).trim();
    if (!value) return;
    const matched =
      mockAnswers.find(item => item.question === value) ||
      (value.includes('现金') ? mockAnswers[1] : undefined) ||
      (value.includes('非经常') || value.includes('扣非') ? mockAnswers[2] : undefined) ||
      (value.includes('偿债') || value.includes('负债') ? mockAnswers[3] : undefined) ||
      (value.includes('费用') || value.includes('利润') ? mockAnswers[0] : undefined);
    setQuery(value);
    setAnswer(
      matched
        ? { ...matched, question: value }
        : {
            question: value,
            answer: '当前示例暂未覆盖这个问题。可以从盈利质量、现金转化或费用压力的研究发现继续查看依据。',
            findingId: 'finding-earnings-quality',
          },
    );
  };
  return (
    <section className={styles.composer} aria-label='Ask DB-GPT'>
      <div className={styles.suggestions}>
        {['利润为何下降？', '现金转化如何？', '非经常性损益'].map((label, index) => (
          <button type='button' key={label} onClick={() => submit(mockAnswers[index].question)}>
            {label}
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
              <Tooltip title='本地示例回答，未调用模型。'>
                <InfoCircleOutlined />
              </Tooltip>
            </span>
            <button type='button' aria-label='收起回答' onClick={() => setAnswer(null)}>
              <CloseOutlined />
            </button>
          </div>
          <p>{answer.answer}</p>
          <button type='button' className={styles.textLink} onClick={() => onOpenEvidence(answer.findingId)}>
            查看回答依据 <ArrowRightOutlined />
          </button>
        </div>
      )}
    </section>
  );
};
export default AskDbGPTDock;
