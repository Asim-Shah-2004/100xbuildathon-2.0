import { Send, Bot } from 'lucide-react';
import useChat from '../../hooks/useChat';
import ChatSidebar from './ChatSidebar';
import ChatMessage from './ChatMessage';
import NewChatModal from './NewChatModal';
import { useState, useEffect } from 'react';
import toast from 'react-hot-toast';
import { motion, AnimatePresence } from 'framer-motion';
import React from 'react';
import { useNavigate } from 'react-router-dom';

const RecruiterChatInterface = () => {
  const {
    chats,
    activeChat,
    showNewChatModal,
    isProcessing,
    roleName,
    jdFile,
    candidatesFile,
    messagesEndRef,
    setActiveChat,
    setShowNewChatModal,
    setMessage,
    setRoleName,
    setJdFile,
    setCandidatesFile,
    createNewChat,
    sendMessage,
    mode,
    setMode
  } = useChat();

  const navigate = useNavigate();
  const [isLoading, setIsLoading] = useState(false);
  const [localMessage, setLocalMessage] = useState(''); // Local state for input
  const [followupLoading, setFollowupLoading] = useState(false);

  // Persistent global chat object
  const [globalChat, setGlobalChat] = useState({
    id: 'global-chat',
    title: 'Global Search',
    roleName: 'Global',
    tableName: '',
    messages: [],
    processed: true,
    createdAt: new Date().toLocaleString(),
    fileName: '',
  });
  // Track previous active chat for restoring after global mode
  const [prevActiveChat, setPrevActiveChat] = useState(null);

  // When switching modes, update active chat accordingly
  useEffect(() => {
    if (mode === 'global') {
      setPrevActiveChat(activeChat);
      setActiveChat(null); // Hide local chat in main area
    } else if (prevActiveChat) {
      setActiveChat(prevActiveChat);
    }
    // eslint-disable-next-line
  }, [mode]);

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  // Send message handler for global chat
  const handleSendMessage = async (msg) => {
    const text = typeof msg === 'string' ? msg : localMessage;
    if (!text.trim()) return;
    setIsLoading(true);
    setFollowupLoading(true);
    setLocalMessage('');
    setMessage('');
    try {
      await sendMessage(text);
    } catch (error) {
      toast.error('Failed to send message');
    } finally {
      setIsLoading(false);
      setFollowupLoading(false);
    }
  };

  // Send message handler for global chat
  const handleSendGlobalMessage = async (msg) => {
    const text = typeof msg === 'string' ? msg : localMessage;
    if (!text.trim()) return;
    setIsLoading(true);
    setFollowupLoading(true);
    setLocalMessage('');
    setMessage('');
    // Add user message
    const userMessage = {
      id: Date.now(),
      type: 'user',
      content: text,
      timestamp: new Date().toLocaleTimeString(),
    };
    const loadingMessage = {
      id: Date.now() + 1,
      type: 'ai',
      content: '',
      isLoading: true,
      timestamp: new Date().toLocaleTimeString(),
    };
    setGlobalChat((prev) => ({
      ...prev,
      messages: [...prev.messages, userMessage, loadingMessage],
    }));
    try {
      const response = await sendMessage(text); // sendMessage uses global mode automatically
      setGlobalChat((prev) => ({
        ...prev,
        messages: [
          ...prev.messages.slice(0, -1),
          {
            id: loadingMessage.id,
            type: 'ai',
            content: response,
            isLoading: false,
            timestamp: new Date().toLocaleTimeString(),
          },
        ],
      }));
    } catch (error) {
      toast.error('Failed to send message');
      setGlobalChat((prev) => ({
        ...prev,
        messages: prev.messages.slice(0, -1),
      }));
    } finally {
      setIsLoading(false);
      setFollowupLoading(false);
    }
  };

  // Add highlight animation effect
  useEffect(() => {
    const interval = setInterval(() => {
      const elements = document.querySelectorAll('.highlight-animation');
      elements.forEach((el) => {
        el.classList.add('highlight');
        setTimeout(() => el.classList.remove('highlight'), 1000);
      });
    }, 5000);

    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (!localStorage.getItem('user_id')) {
      navigate('/login');
    }
  }, [navigate]);

  const handleLogout = () => {
    localStorage.removeItem('user_id');
    navigate('/login');
  };

  // Add a fallback for global mode: if no activeChat, create a temporary one
  const ensureActiveChat = () => {
    if (!activeChat && mode === 'global') {
      const tempChat = {
        id: 'global-temp',
        title: 'Global Search',
        roleName: 'Global',
        tableName: '',
        messages: [],
        processed: true,
        createdAt: new Date().toLocaleString(),
        fileName: '',
      };
      setActiveChat(tempChat);
      return tempChat;
    }
    return activeChat;
  };
  const currentChat = ensureActiveChat();

  return (
    <div className="flex h-screen bg-[#000000] font-['Inter'] overflow-hidden">
      <ChatSidebar
        chats={chats}
        activeChat={activeChat}
        onChatSelect={setActiveChat}
        onNewChat={() => setShowNewChatModal(true)}
      />

      {/* Main Content */}
      <div className="flex-1 flex flex-col h-screen">
        {/* Mode Toggle - always visible */}
        <div className="flex items-center justify-end gap-4 p-4 bg-[#111] border-b border-[#222] z-20">
          <span className="text-[#aaa] text-sm">Mode:</span>
          <button
            onClick={() => setMode('database')}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-all duration-200 ${mode === 'database' ? 'bg-[#fff] text-[#000]' : 'bg-[#222] text-[#aaa]'}`}
          >
            Database Mode
          </button>
          <button
            onClick={() => setMode('global')}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-all duration-200 ${mode === 'global' ? 'bg-[#fff] text-[#000]' : 'bg-[#222] text-[#aaa]'}`}
          >
            Global Mode
          </button>
        </div>
        <AnimatePresence mode="wait">
          {mode === 'global' ? (
            /* Dedicated Global Chat */
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="flex-1 flex flex-col h-full"
            >
              {/* Chat Header - Fixed at top */}
              <motion.div
                initial={{ y: -20, opacity: 0 }}
                animate={{ y: 0, opacity: 1 }}
                className="border-b border-[#808080]/20 p-6 bg-[#000000]/50 backdrop-blur-sm sticky top-0 z-10"
              >
                <div className="flex items-center justify-between">
                  <div>
                    <h2 className="text-2xl font-semibold text-[#FFFFFF]">{globalChat.title}</h2>
                    <p className="text-sm text-[#808080]">Ask about anyone, anywhere in the world.</p>
                  </div>
                  <div className="flex items-center gap-3">
                    <button
                      onClick={handleLogout}
                      className="px-4 py-2 bg-primary text-primary-foreground rounded-lg shadow hover:bg-primary/90 transition"
                    >
                      Logout
                    </button>
                  </div>
                </div>
              </motion.div>
              {/* Messages - Scrollable */}
              <div className="flex-1 overflow-y-auto p-6">
                <AnimatePresence>
                  {globalChat.messages.length === 0 ? (
                    <motion.div
                      initial={{ opacity: 0, y: 20 }}
                      animate={{ opacity: 1, y: 0 }}
                      className="text-center py-12"
                    >
                      <Bot size={48} className="mx-auto mb-4 text-[#808080]" />
                      <p className="text-[#FFFFFF] mb-2 text-lg">Ready to search globally!</p>
                      <p className="text-sm text-[#808080]">Ask about people, roles, or companies worldwide.</p>
                    </motion.div>
                  ) : (
                    <div className="space-y-6">
                      {globalChat.messages.map((message, index) => (
                        <motion.div
                          key={index}
                          initial={{ opacity: 0, y: 20 }}
                          animate={{ opacity: 1, y: 0 }}
                          transition={{ delay: index * 0.1 }}
                        >
                          <ChatMessage
                            message={message}
                            isLoading={message.isLoading}
                            onFollowup={followupLoading ? undefined : handleSendGlobalMessage}
                          />
                        </motion.div>
                      ))}
                    </div>
                  )}
                </AnimatePresence>
              </div>
              {/* Input Area - Fixed at bottom */}
              <MemoizedInputArea
                message={localMessage}
                setMessage={setLocalMessage}
                handleKeyPress={handleKeyPress}
                handleSendMessage={handleSendGlobalMessage}
                disabled={isLoading || followupLoading}
              />
            </motion.div>
          ) : (
            /* Chat Interface */
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="flex-1 flex flex-col h-full"
            >
              {/* Chat Header - Fixed at top */}
              <motion.div
                initial={{ y: -20, opacity: 0 }}
                animate={{ y: 0, opacity: 1 }}
                className="border-b border-[#808080]/20 p-6 bg-[#000000]/50 backdrop-blur-sm sticky top-0 z-10"
              >
                <div className="flex items-center justify-between">
                  {/* Left: Title and subtitle */}
                  <div>
                    <h2 className="text-2xl font-semibold text-[#FFFFFF]">{currentChat.title}</h2>
                    <p className="text-sm text-[#808080]">
                      {mode === 'global' ? 'Ask about anyone, anywhere in the world.' : `Analyzing data from ${currentChat.fileName}`}
                    </p>
                  </div>
                  {/* Right: Buttons */}
                  <div className="flex items-center gap-3">
                    {mode !== 'global' && (
                      <button
                        onClick={() => navigate(`/dashboard?table=${currentChat.tableName}`)}
                        className="px-6 py-2 bg-[#FFFFFF] text-[#000000] hover:bg-[#FFFFFF]/90 rounded-lg transition-all duration-300 text-base font-medium shadow hover:shadow-lg"
                      >
                        View Insights
                      </button>
                    )}
                    <button
                      onClick={handleLogout}
                      className="px-4 py-2 bg-primary text-primary-foreground rounded-lg shadow hover:bg-primary/90 transition"
                    >
                      Logout
                    </button>
                  </div>
                </div>
              </motion.div>

              {/* Messages - Scrollable */}
              <div className="flex-1 overflow-y-auto p-6">
                <AnimatePresence>
                  {currentChat.messages.length === 0 ? (
                    <motion.div
                      initial={{ opacity: 0, y: 20 }}
                      animate={{ opacity: 1, y: 0 }}
                      className="text-center py-12"
                    >
                      <Bot size={48} className="mx-auto mb-4 text-[#808080]" />
                      <p className="text-[#FFFFFF] mb-2 text-lg">{mode === 'global' ? 'Ready to search globally!' : 'Ready to analyze your data!'}</p>
                      <p className="text-sm text-[#808080]">
                        {mode === 'global' ? 'Ask about people, roles, or companies worldwide.' : 'Ask questions about candidate insights, skills analysis, or hiring recommendations.'}
                      </p>
                    </motion.div>
                  ) : (
                    <div className="space-y-6">
                      {currentChat.messages.map((message, index) => (
                        <motion.div
                          key={index}
                          initial={{ opacity: 0, y: 20 }}
                          animate={{ opacity: 1, y: 0 }}
                          transition={{ delay: index * 0.1 }}
                        >
                          <ChatMessage
                            message={message}
                            isLoading={message.isLoading}
                            onFollowup={followupLoading ? undefined : handleSendMessage}
                          />
                        </motion.div>
                      ))}
                    </div>
                  )}
                </AnimatePresence>
                <div ref={messagesEndRef} />
              </div>

              {/* Input Area - Fixed at bottom */}
              <MemoizedInputArea
                message={localMessage}
                setMessage={setLocalMessage}
                handleKeyPress={handleKeyPress}
                handleSendMessage={handleSendMessage}
                disabled={isLoading || followupLoading}
              />
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      <NewChatModal
        isOpen={showNewChatModal}
        onClose={() => {
          setShowNewChatModal(false);
          setRoleName('');
          setJdFile(null);
          setCandidatesFile(null);
        }}
        onCreate={createNewChat}
        isProcessing={isProcessing}
        roleName={roleName}
        setRoleName={setRoleName}
        jdFile={jdFile}
        setJdFile={setJdFile}
        candidatesFile={candidatesFile}
        setCandidatesFile={setCandidatesFile}
      />
    </div>
  );
};

// Update the MemoizedInputArea component
const MemoizedInputArea = React.memo(({ message: localMessage, setMessage: setLocalMessage, handleKeyPress, handleSendMessage, disabled }) => {
  return (
    <motion.div
      initial={{ y: 20, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      className="border-t border-[#808080]/20 p-6 bg-[#000000]/50 backdrop-blur-sm sticky bottom-0 z-10"
    >
      <div className="flex gap-3">
        <div className="flex-1 relative">
          <textarea
            value={localMessage}
            onChange={(e) => setLocalMessage(e.target.value)}
            onKeyPress={handleKeyPress}
            placeholder="Ask about candidate insights, skills analysis, or hiring recommendations..."
            className="w-full p-4 pr-12 bg-[#000000] text-[#FFFFFF] border border-[#808080]/20 rounded-xl resize-none focus:outline-none focus:ring-2 focus:ring-[#FFFFFF]/20 focus:border-transparent placeholder-[#808080]"
            rows={1}
            style={{ minHeight: '56px' }}
            disabled={disabled}
          />
        </div>
        <motion.button
          whileHover={{ scale: 1.05 }}
          whileTap={{ scale: 0.95 }}
          onClick={handleSendMessage}
          disabled={!localMessage.trim() || disabled}
          className="px-4 py-4 bg-[#FFFFFF] text-[#000000] hover:bg-[#FFFFFF]/90 disabled:bg-[#808080]/20 disabled:text-[#808080] disabled:cursor-not-allowed rounded-xl transition-all duration-300"
        >
          <Send size={20} />
        </motion.button>
      </div>
    </motion.div>
  );
});

export default RecruiterChatInterface; 