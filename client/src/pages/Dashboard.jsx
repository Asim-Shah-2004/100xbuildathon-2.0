import { useState, useEffect, useRef } from "react";
import InsightsDashboard from "@/components/InsightsDashboard/InsightsDashboard";
import { Card, CardContent } from "@/components/ui/card";
import { motion, AnimatePresence } from "framer-motion";
import { User, X, BarChart2, ChevronDown } from "lucide-react";
import axios from "axios";
import { useSearchParams } from "react-router-dom";

const TableDropdown = ({ tables, selectedTable, onSelect }) => {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef(null);

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setIsOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleSelect = (table) => {
    onSelect(table);
    setIsOpen(false);
  };

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="px-4 py-2 bg-[#FFFFFF]/10 text-[#FFFFFF] rounded-lg hover:bg-[#FFFFFF]/20 flex items-center gap-2 min-w-[200px] justify-between"
      >
        <span className="truncate">{selectedTable || "Select Table"}</span>
        <ChevronDown
          size={16}
          className={`transition-transform duration-200 ${isOpen ? 'rotate-180' : ''}`}
        />
      </button>

      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            transition={{ duration: 0.2 }}
            className="absolute top-full left-0 mt-2 w-full bg-[#000000] border border-[#808080]/20 rounded-lg shadow-lg z-50"
          >
            <div className="max-h-60 overflow-y-auto">
              {tables.map((table) => (
                <button
                  key={table}
                  type="button"
                  onClick={() => handleSelect(table)}
                  className={`w-full px-4 py-2 text-left hover:bg-[#FFFFFF]/10 ${table === selectedTable ? 'bg-[#FFFFFF]/20' : ''
                    }`}
                >
                  <span className="text-[#FFFFFF] truncate block">{table}</span>
                </button>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

const Dashboard = () => {
  const [tableData, setTableData] = useState(null);
  const [selectedCandidate, setSelectedCandidate] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [tableName, setTableName] = useState("");
  const [availableTables, setAvailableTables] = useState([]);
  const [searchParams] = useSearchParams();

  useEffect(() => {
    fetchTableName();
  }, []);

  useEffect(() => {
    const tableFromUrl = searchParams.get('table');
    if (tableFromUrl && availableTables.includes(tableFromUrl)) {
      handleTableSelect(tableFromUrl);
    }
  }, [searchParams, availableTables]);

  const fetchTableName = async () => {
    try {
      setLoading(true);
      const response = await axios.get(`${import.meta.env.VITE_BACKEND_URL}/gettables`, {
        headers: {
          'ngrok-skip-browser-warning': 'true',
          'Accept': 'application/json'
        }
      });
      console.log("Tables response:", response.data);

      // Check if response has the expected format
      if (response.data && response.data.tables) {
        // Filter out system tables and sort by timestamp (newest first)
        const userTables = response.data.tables
          .filter(tableName => !['rejected_candidates', 'candidates'].includes(tableName))
          .sort((a, b) => {
            // Extract timestamps from table names if they exist
            const getTimestamp = (name) => {
              const parts = name.split('_');
              const lastPart = parts[parts.length - 1];
              return !isNaN(lastPart) ? parseInt(lastPart) : 0;
            };
            return getTimestamp(b) - getTimestamp(a);
          });

        if (userTables.length > 0) {
          setAvailableTables(userTables);
          setError(null);
        } else {
          setError("No analysis tables found. Please create a new analysis first.");
          setAvailableTables([]);
        }
      } else {
        setError("Invalid response format from server");
        setAvailableTables([]);
      }
    } catch (err) {
      console.error("Error fetching tables:", err);
      setError("Failed to fetch tables. Please try again later.");
      setAvailableTables([]);
    } finally {
      setLoading(false);
    }
  };

  const handleTableSelect = (table) => {
    setTableName(table);
    setSelectedCandidate(null);
    fetchTableData(table);
  };

  const fetchTableData = async (table) => {
    try {
      setLoading(true);
      const response = await axios.get(`${import.meta.env.VITE_BACKEND_URL}/insights?tableName=${table}`, {
        headers: {
          'ngrok-skip-browser-warning': 'true',
          'Accept': 'application/json'
        }
      });
      setTableData(response.data);
      setError(null);
    } catch (err) {
      setError("Failed to fetch data");
      console.error("Error fetching data:", err);
    } finally {
      setLoading(false);
    }
  };

  const fetchCandidateDetails = async (name) => {
    try {
      const response = await axios.get(`${import.meta.env.VITE_BACKEND_URL}/candidate/${encodeURIComponent(name)}`, {
        headers: {
          'ngrok-skip-browser-warning': 'true',
          'Accept': 'application/json'
        }
      });
      setSelectedCandidate(response.data);
    } catch (err) {
      console.error("Error fetching candidate details:", err);
    }
  };

  const generateCharts = () => {
    if (!tableData?.data || !tableData?.columns) return [];

    const charts = [];
    const data = tableData.data;
    const columns = tableData.columns;

    // Helper function to check if a column contains numeric data
    const isNumericColumn = (columnName) => {
      return data.some(row => {
        const value = row[columnName];
        return !isNaN(parseFloat(value)) && isFinite(value);
      });
    };

    // Helper function to check if a column contains categorical data
    const isCategoricalColumn = (columnName) => {
      const uniqueValues = new Set(data.map(row => row[columnName]));
      return uniqueValues.size <= 10; // Consider it categorical if it has 10 or fewer unique values
    };

    // Generate score distribution chart
    const scoreColumn = columns.find(col =>
      col.toLowerCase().includes('score') ||
      col.toLowerCase().includes('rating') ||
      col.toLowerCase().includes('match')
    );

    if (scoreColumn && isNumericColumn(scoreColumn)) {
      const ranges = {
        "90-100": 0,
        "80-89": 0,
        "70-79": 0,
        "60-69": 0,
        "0-59": 0
      };

      data.forEach(row => {
        const score = parseFloat(row[scoreColumn]);
        if (score >= 90) ranges["90-100"]++;
        else if (score >= 80) ranges["80-89"]++;
        else if (score >= 70) ranges["70-79"]++;
        else if (score >= 60) ranges["60-69"]++;
        else ranges["0-59"]++;
      });

      charts.push({
        type: "bar",
        data: {
          title: "Candidate Score Distribution",
          categories: Object.keys(ranges),
          yAxisTitle: "Number of Candidates",
          series: [{
            name: "Score Range",
            data: Object.values(ranges)
          }]
        }
      });
    }

    // Generate skills distribution chart
    const skillsColumn = columns.find(col =>
      col.toLowerCase().includes('skill') ||
      col.toLowerCase().includes('expertise')
    );

    if (skillsColumn) {
      const skillCounts = {};
      data.forEach(row => {
        const skills = row[skillsColumn]?.split(',').map(s => s.trim()) || [];
        skills.forEach(skill => {
          if (skill) {
            skillCounts[skill] = (skillCounts[skill] || 0) + 1;
          }
        });
      });

      const topSkills = Object.entries(skillCounts)
        .sort(([, a], [, b]) => b - a)
        .slice(0, 10)
        .map(([skill, count]) => ({
          name: skill,
          y: count
        }));

      if (topSkills.length > 0) {
        charts.push({
          type: "pie",
          data: {
            title: "Top Skills Distribution",
            seriesName: "Skills",
            data: topSkills
          }
        });
      }
    }

    // Generate experience level distribution
    const experienceColumn = columns.find(col =>
      col.toLowerCase().includes('experience') ||
      col.toLowerCase().includes('years')
    );

    if (experienceColumn) {
      const experienceRanges = {
        "10+ years": 0,
        "5-10 years": 0,
        "3-5 years": 0,
        "1-3 years": 0,
        "< 1 year": 0
      };

      data.forEach(row => {
        const exp = row[experienceColumn]?.toLowerCase() || '';
        if (exp.includes('10') || exp.includes('ten')) experienceRanges["10+ years"]++;
        else if (exp.includes('5') || exp.includes('five')) experienceRanges["5-10 years"]++;
        else if (exp.includes('3') || exp.includes('three')) experienceRanges["3-5 years"]++;
        else if (exp.includes('1') || exp.includes('one')) experienceRanges["1-3 years"]++;
        else experienceRanges["< 1 year"]++;
      });

      charts.push({
        type: "bar",
        data: {
          title: "Experience Level Distribution",
          categories: Object.keys(experienceRanges),
          yAxisTitle: "Number of Candidates",
          series: [{
            name: "Experience Range",
            data: Object.values(experienceRanges)
          }]
        }
      });
    }

    // Generate education level distribution
    const educationColumn = columns.find(col =>
      col.toLowerCase().includes('education') ||
      col.toLowerCase().includes('degree')
    );

    if (educationColumn) {
      const educationLevels = {};
      data.forEach(row => {
        const education = row[educationColumn]?.toLowerCase() || '';
        if (education.includes('phd') || education.includes('doctorate')) {
          educationLevels['PhD'] = (educationLevels['PhD'] || 0) + 1;
        } else if (education.includes('master') || education.includes('ms') || education.includes('mba')) {
          educationLevels['Masters'] = (educationLevels['Masters'] || 0) + 1;
        } else if (education.includes('bachelor') || education.includes('bs') || education.includes('ba')) {
          educationLevels['Bachelors'] = (educationLevels['Bachelors'] || 0) + 1;
        } else {
          educationLevels['Other'] = (educationLevels['Other'] || 0) + 1;
        }
      });

      charts.push({
        type: "pie",
        data: {
          title: "Education Level Distribution",
          seriesName: "Education",
          data: Object.entries(educationLevels).map(([level, count]) => ({
            name: level,
            y: count
          }))
        }
      });
    }

    return charts;
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-[#000000] p-6 flex items-center justify-center">
        <div className="text-center">
          <motion.div
            animate={{
              rotate: 360,
              scale: [1, 1.2, 1],
            }}
            transition={{
              duration: 2,
              repeat: Infinity,
              ease: "linear"
            }}
            className="w-16 h-16 border-4 border-[#FFFFFF] border-t-transparent rounded-full mx-auto mb-6"
          />
          <h2 className="text-2xl font-bold text-[#FFFFFF]">Loading Tables...</h2>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-[#000000] p-6 flex items-center justify-center">
        <div className="text-center max-w-md">
          <h2 className="text-2xl font-bold text-[#FFFFFF] mb-4">{error}</h2>
          <p className="text-[#808080] mb-6">
            {error.includes("No tables found")
              ? "You need to create a new analysis first. Go to the chat interface to start analyzing candidates."
              : "Please try again later or contact support if the issue persists."}
          </p>
          {error.includes("No tables found") && (
            <motion.button
              whileHover={{ scale: 1.05 }}
              whileTap={{ scale: 0.95 }}
              onClick={() => window.location.href = '/chat'}
              className="px-6 py-3 bg-[#FFFFFF] text-[#000000] rounded-lg hover:bg-[#FFFFFF]/90"
            >
              Go to Chat Interface
            </motion.button>
          )}
          {!error.includes("No tables found") && (
            <motion.button
              whileHover={{ scale: 1.05 }}
              whileTap={{ scale: 0.95 }}
              onClick={fetchTableName}
              className="px-6 py-3 bg-[#FFFFFF] text-[#000000] rounded-lg hover:bg-[#FFFFFF]/90"
            >
              Retry
            </motion.button>
          )}
        </div>
      </div>
    );
  }

  // Show table selection screen if no table is selected
  if (!tableName) {
    return (
      <div className="min-h-screen bg-[#000000] p-6 flex items-center justify-center">
        <div className="max-w-2xl w-full">
          <h1 className="text-3xl font-bold text-[#FFFFFF] mb-8 text-center">Select a Table</h1>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {availableTables.map((table) => (
              <motion.button
                key={table}
                whileHover={{ scale: 1.02 }}
                whileTap={{ scale: 0.98 }}
                onClick={() => handleTableSelect(table)}
                className="p-6 bg-[#000000] border border-[#808080]/20 rounded-lg hover:bg-[#FFFFFF]/5 text-left"
              >
                <h3 className="text-xl font-semibold text-[#FFFFFF] mb-2">{table}</h3>
                <p className="text-[#808080]">Click to view insights</p>
              </motion.button>
            ))}
          </div>
        </div>
      </div>
    );
  }

  // Show loading state while fetching table data
  if (!tableData) {
    return (
      <div className="min-h-screen bg-[#000000] p-6 flex items-center justify-center">
        <div className="text-center">
          <motion.div
            animate={{
              rotate: 360,
              scale: [1, 1.2, 1],
            }}
            transition={{
              duration: 2,
              repeat: Infinity,
              ease: "linear"
            }}
            className="w-16 h-16 border-4 border-[#FFFFFF] border-t-transparent rounded-full mx-auto mb-6"
          />
          <h2 className="text-2xl font-bold text-[#FFFFFF]">Loading Dashboard...</h2>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#000000] p-6">
      <div className="mb-8">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-4">
            <h1 className="text-3xl font-bold text-[#FFFFFF]">Insights Dashboard</h1>
            <TableDropdown
              tables={availableTables}
              selectedTable={tableName}
              onSelect={handleTableSelect}
            />
          </div>
          <div className="flex gap-4">
            <motion.button
              whileHover={{ scale: 1.05 }}
              whileTap={{ scale: 0.95 }}
              onClick={() => window.location.href = '/chat'}
              className="px-4 py-2 bg-[#FFFFFF]/10 text-[#FFFFFF] rounded-lg hover:bg-[#FFFFFF]/20 flex items-center gap-2"
            >
              Back to Home
            </motion.button>
            <motion.button
              whileHover={{ scale: 1.05 }}
              whileTap={{ scale: 0.95 }}
              className="px-4 py-2 bg-[#FFFFFF] text-[#000000] rounded-lg hover:bg-[#FFFFFF]/90 flex items-center gap-2"
              onClick={() => fetchTableData(tableName)}
            >
              <BarChart2 size={20} />
              Refresh Data
            </motion.button>
            <motion.button
              whileHover={{ scale: 1.05 }}
              whileTap={{ scale: 0.95 }}
              className="px-4 py-2 bg-[#FFFFFF]/10 text-[#FFFFFF] rounded-lg hover:bg-[#FFFFFF]/20 flex items-center gap-2"
              onClick={() => {
                setTableName("");
                setTableData(null);
                setSelectedCandidate(null);
              }}
            >
              Change Table
            </motion.button>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Main Dashboard */}
        <div className="lg:col-span-2">
          {tableData?.data ? (
            <InsightsDashboard charts={generateCharts()} />
          ) : (
            <div className="bg-[#000000] border border-[#808080]/20 rounded-lg p-6">
              <p className="text-[#808080]">No data available to display charts.</p>
            </div>
          )}
        </div>

        {/* Candidate List */}
        <div className="space-y-4">
          <h2 className="text-xl font-semibold text-[#FFFFFF] mb-4">Candidates</h2>
          <div className="space-y-4 max-h-[calc(100vh-200px)] overflow-y-auto">
            {tableData?.data ? (
              tableData.data.map((candidate) => (
                <motion.div
                  key={candidate.name}
                  whileHover={{ scale: 1.02 }}
                  whileTap={{ scale: 0.98 }}
                  onClick={() => fetchCandidateDetails(candidate.name)}
                  className="bg-[#000000] border border-[#808080]/20 rounded-lg p-4 cursor-pointer hover:bg-[#FFFFFF]/5"
                >
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 bg-[#FFFFFF]/10 rounded-full flex items-center justify-center">
                      <User size={20} className="text-[#FFFFFF]" />
                    </div>
                    <div>
                      <h3 className="font-medium text-[#FFFFFF]">{candidate.name}</h3>
                      <p className="text-sm text-[#808080]">{candidate.email}</p>
                    </div>
                    <div className="ml-auto">
                      <span className="px-2 py-1 bg-[#FFFFFF]/10 text-[#FFFFFF] rounded text-sm">
                        Score: {candidate.score}
                      </span>
                    </div>
                  </div>
                </motion.div>
              ))
            ) : (
              <div className="bg-[#000000] border border-[#808080]/20 rounded-lg p-4">
                <p className="text-[#808080]">No candidates available.</p>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Candidate Details Modal */}
      <AnimatePresence>
        {selectedCandidate && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-[#000000]/95 backdrop-blur-sm z-50 flex items-center justify-center p-4"
          >
            <motion.div
              initial={{ scale: 0.9, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.9, opacity: 0 }}
              className="bg-[#000000] rounded-2xl shadow-2xl w-full max-w-4xl max-h-[90vh] overflow-y-auto border border-[#808080]/20"
            >
              <div className="p-8">
                <div className="flex justify-between items-start mb-8">
                  <div>
                    <h2 className="text-3xl font-bold text-[#FFFFFF]">{selectedCandidate.name}</h2>
                    <p className="text-[#808080] mt-2">{selectedCandidate.email}</p>
                  </div>
                  <motion.button
                    whileHover={{ scale: 1.1, rotate: 90 }}
                    whileTap={{ scale: 0.9 }}
                    onClick={() => setSelectedCandidate(null)}
                    className="text-[#808080] hover:text-[#FFFFFF] transition-colors"
                  >
                    <X size={28} />
                  </motion.button>
                </div>

                <div className="grid grid-cols-2 gap-6">
                  <Card className="bg-[#000000] border-[#808080]/20">
                    <CardContent className="p-6">
                      <h3 className="text-xl font-semibold text-[#FFFFFF] mb-4">Contact Information</h3>
                      <div className="space-y-2">
                        <p className="text-[#808080]">Phone: {selectedCandidate.phone}</p>
                        <p className="text-[#808080]">LinkedIn: {selectedCandidate.linkedin}</p>
                        <p className="text-[#808080]">Address: {selectedCandidate.address}</p>
                      </div>
                    </CardContent>
                  </Card>

                  <Card className="bg-[#000000] border-[#808080]/20">
                    <CardContent className="p-6">
                      <h3 className="text-xl font-semibold text-[#FFFFFF] mb-4">Education</h3>
                      <div className="space-y-2">
                        <p className="text-[#808080]">{selectedCandidate.education}</p>
                        <p className="text-[#808080]">Degree: {selectedCandidate.degree}</p>
                        <p className="text-[#808080]">Major: {selectedCandidate.major}</p>
                        <p className="text-[#808080]">GPA: {selectedCandidate.gpa}</p>
                      </div>
                    </CardContent>
                  </Card>

                  <Card className="bg-[#000000] border-[#808080]/20 col-span-2">
                    <CardContent className="p-6">
                      <h3 className="text-xl font-semibold text-[#FFFFFF] mb-4">Experience</h3>
                      <div className="space-y-4">
                        <p className="text-[#808080] whitespace-pre-line">{selectedCandidate.experience}</p>
                      </div>
                    </CardContent>
                  </Card>

                  <Card className="bg-[#000000] border-[#808080]/20 col-span-2">
                    <CardContent className="p-6">
                      <h3 className="text-xl font-semibold text-[#FFFFFF] mb-4">Skills</h3>
                      <div className="flex flex-wrap gap-2">
                        {selectedCandidate.skills?.split(",").map((skill, index) => (
                          <span
                            key={index}
                            className="px-3 py-1 bg-[#FFFFFF]/10 text-[#FFFFFF] rounded-full text-sm"
                          >
                            {skill.trim()}
                          </span>
                        ))}
                      </div>
                    </CardContent>
                  </Card>
                </div>

                {/* Highlighted Resume Button and Color Legend */}
                {selectedCandidate.highlighted_pdf_url && (
                  <div className="mt-8 flex flex-col items-center">
                    <a
                      href={`${import.meta.env.VITE_BACKEND_URL}/highlighted_resume/${selectedCandidate.highlighted_pdf_url}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="px-6 py-3 bg-[#FFD600] text-[#000] rounded-lg font-semibold shadow hover:bg-[#FFEA70] transition mb-4"
                    >
                      View Highlighted Resume (PDF)
                    </a>
                    <div className="flex flex-wrap gap-4 justify-center mt-2">
                      <div className="flex items-center gap-2"><span className="w-4 h-4 rounded bg-yellow-300 inline-block"></span><span className="text-[#fff] text-sm">Name/Email</span></div>
                      <div className="flex items-center gap-2"><span className="w-4 h-4 rounded bg-cyan-300 inline-block"></span><span className="text-[#fff] text-sm">Skills</span></div>
                      <div className="flex items-center gap-2"><span className="w-4 h-4 rounded bg-pink-400 inline-block"></span><span className="text-[#fff] text-sm">Experience</span></div>
                      <div className="flex items-center gap-2"><span className="w-4 h-4 rounded bg-orange-400 inline-block"></span><span className="text-[#fff] text-sm">Education</span></div>
                      {/* Add more legend items if needed */}
                    </div>
                  </div>
                )}
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default Dashboard;
