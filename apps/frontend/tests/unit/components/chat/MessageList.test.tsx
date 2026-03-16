import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MessageList } from '@/components/chat/MessageList';

const mockMessages = [
  { id: '1', role: 'user' as const, content: 'Hello there!' },
  { id: '2', role: 'assistant' as const, content: 'Hi! How can I help you?' },
  { id: '3', role: 'user' as const, content: 'What is the weather?' },
];

describe('MessageList', () => {
  beforeEach(() => {
    Element.prototype.scrollIntoView = vi.fn();
  });

  describe('rendering', () => {
    it('renders all messages', () => {
      render(<MessageList messages={mockMessages} />);

      expect(screen.getByText('Hello there!')).toBeInTheDocument();
      expect(screen.getByText('Hi! How can I help you?')).toBeInTheDocument();
      expect(screen.getByText('What is the weather?')).toBeInTheDocument();
    });

    it('renders container when no messages', () => {
      const { container } = render(<MessageList messages={[]} />);
      expect(container.querySelector('.space-y-10')).toBeInTheDocument();
    });

    it('preserves whitespace in messages', () => {
      const multilineContent = 'Line 1\nLine 2\nLine 3';
      const { container } = render(
        <MessageList messages={[{ id: '1', role: 'user', content: multilineContent }]} />
      );

      const messageElement = container.querySelector('.whitespace-pre-wrap');
      expect(messageElement).toBeInTheDocument();
      expect(messageElement).toHaveTextContent('Line 1');
      expect(messageElement).toHaveTextContent('Line 2');
      expect(messageElement).toHaveTextContent('Line 3');
    });
  });

  describe('message alignment', () => {
    it('aligns user messages to the right', () => {
      render(<MessageList messages={[{ id: '1', role: 'user', content: 'User message' }]} />);

      const messageWrapper = screen.getByText('User message').closest('.flex');
      expect(messageWrapper).toHaveClass('items-end');
    });

    it('aligns assistant messages to the left', () => {
      render(<MessageList messages={[{ id: '1', role: 'assistant', content: 'Assistant message' }]} />);

      const messageWrapper = screen.getByText('Assistant message').closest('.flex');
      expect(messageWrapper).toHaveClass('items-start');
    });
  });

  describe('message styling', () => {
    it('applies correct text style to user messages', () => {
      render(<MessageList messages={[{ id: '1', role: 'user', content: 'User message' }]} />);

      const messageText = screen.getByText('User message').closest('.text-sm');
      expect(messageText).toHaveClass('text-white');
    });

    it('applies correct text style to assistant messages', () => {
      render(<MessageList messages={[{ id: '1', role: 'assistant', content: 'Assistant message' }]} />);

      const messageText = screen.getByText('Assistant message').closest('.text-sm');
      expect(messageText).toBeInTheDocument();
    });
  });

  describe('typing indicator', () => {
    it('shows for empty assistant message when isTyping', () => {
      render(
        <MessageList
          messages={[{ id: '1', role: 'assistant', content: '' }]}
          isTyping={true}
        />
      );

      const dots = document.querySelectorAll('.animate-bounce');
      expect(dots.length).toBe(3);
    });

    it('hides when not typing', () => {
      render(
        <MessageList
          messages={[{ id: '1', role: 'assistant', content: '' }]}
          isTyping={false}
        />
      );

      const dots = document.querySelectorAll('.animate-bounce');
      expect(dots.length).toBe(0);
    });

    it('never shows for user messages', () => {
      render(
        <MessageList
          messages={[{ id: '1', role: 'user', content: '' }]}
          isTyping={true}
        />
      );

      const dots = document.querySelectorAll('.animate-bounce');
      expect(dots.length).toBe(0);
    });
  });

  describe('auto-scroll', () => {
    it('renders scroll anchor element at end of messages', () => {
      // The useScrollToBottom hook provides refs for CSS-based scrolling
      // The endRef element acts as a scroll anchor
      const { container } = render(
        <MessageList messages={[{ id: '1', role: 'user', content: 'Test message' }]} />
      );

      // Verify the scroll container and end anchor exist
      const scrollContainer = container.querySelector('[data-lenis-prevent]');
      expect(scrollContainer).toBeInTheDocument();

      // The end ref div should exist after messages
      const messageContainer = container.querySelector('.space-y-10');
      expect(messageContainer).toBeInTheDocument();
      expect(messageContainer?.lastElementChild?.tagName).toBe('DIV');
    });
  });
});
