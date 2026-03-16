import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ChatInput } from '@/components/chat/ChatInput';

describe('ChatInput', () => {
  const mockOnSend = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  function getTextarea(): HTMLElement {
    return screen.getByPlaceholderText('Ask anything');
  }

  function getSendButton(): HTMLElement {
    return screen.getByTestId('send-button');
  }

  describe('rendering', () => {
    it('renders textarea and send button', () => {
      render(<ChatInput onSend={mockOnSend} />);

      expect(getTextarea()).toBeInTheDocument();
      expect(getSendButton()).toBeInTheDocument();
    });

    it('applies backdrop-blur class when not centered', () => {
      const { container } = render(<ChatInput onSend={mockOnSend} />);
      expect(container.firstChild).toHaveClass('backdrop-blur-md');
    });

    it('omits backdrop-blur class when centered', () => {
      const { container } = render(<ChatInput onSend={mockOnSend} centered />);
      expect(container.firstChild).not.toHaveClass('backdrop-blur-md');
    });
  });

  describe('sending messages', () => {
    it('calls onSend with input value on button click', async () => {
      const user = userEvent.setup();
      render(<ChatInput onSend={mockOnSend} />);

      await user.type(getTextarea(), 'Hello world');
      await user.click(getSendButton());

      expect(mockOnSend).toHaveBeenCalledWith('Hello world', undefined);
    });

    it('clears input after send', async () => {
      const user = userEvent.setup();
      render(<ChatInput onSend={mockOnSend} />);

      const textarea = getTextarea();
      await user.type(textarea, 'Test message');
      await user.click(getSendButton());

      expect(textarea).toHaveValue('');
    });

    it('sends on Enter key', async () => {
      const user = userEvent.setup();
      render(<ChatInput onSend={mockOnSend} />);

      await user.type(getTextarea(), 'Enter test');
      await user.keyboard('{Enter}');

      expect(mockOnSend).toHaveBeenCalledWith('Enter test', undefined);
    });

    it('does not send on Shift+Enter', async () => {
      const user = userEvent.setup();
      render(<ChatInput onSend={mockOnSend} />);

      await user.type(getTextarea(), 'Shift enter test');
      await user.keyboard('{Shift>}{Enter}{/Shift}');

      expect(mockOnSend).not.toHaveBeenCalled();
    });
  });

  describe('validation', () => {
    it('does not send when input is empty', async () => {
      const user = userEvent.setup();
      render(<ChatInput onSend={mockOnSend} />);

      await user.click(getSendButton());

      expect(mockOnSend).not.toHaveBeenCalled();
    });

    it('does not send when input is only whitespace', async () => {
      const user = userEvent.setup();
      render(<ChatInput onSend={mockOnSend} />);

      await user.type(getTextarea(), '   ');
      await user.click(getSendButton());

      expect(mockOnSend).not.toHaveBeenCalled();
    });
  });

  describe('disabled state', () => {
    it('disables textarea when disabled', () => {
      render(<ChatInput onSend={mockOnSend} disabled />);
      expect(getTextarea()).toBeDisabled();
    });

    it('disables send button when disabled', () => {
      render(<ChatInput onSend={mockOnSend} disabled />);
      expect(getSendButton()).toBeDisabled();
    });

    it('disables send button when input is empty', () => {
      render(<ChatInput onSend={mockOnSend} />);
      expect(getSendButton()).toBeDisabled();
    });

    it('enables send button when input has content', async () => {
      const user = userEvent.setup();
      render(<ChatInput onSend={mockOnSend} />);

      await user.type(getTextarea(), 'Test');

      expect(getSendButton()).not.toBeDisabled();
    });
  });
});
