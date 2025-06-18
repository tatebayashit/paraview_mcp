# Paraview_MCP

ParaView-MCP is an autonomous agent that integrates multimodal large language models with ParaView through the Model Context Protocol, enabling users to create and manipulate scientific visualizations using natural language and visual inputs instead of complex commands or GUI operations. The system features visual feedback capabilities that allow it to observe the viewport and iteratively refine visualizations, making advanced visualization accessible to non-experts while augmenting expert workflows with intelligent automation.

## Installation

```shell
git clone https://github.com/LLNL/paraview_mcp.git
cd paraview_mcp

conda create -n paraview_mcp python=3.10
conda install conda-forge::paraview
conda install mcp[cli] httpx
```

## Setup for LLM

To set up integration with claude desktop, add the following to claude_desktop_config.json

```json
    "mcpServers": {
      "ParaView": {
        "command": "/path/to/python",
        "args": [
        "/path/to/paraview_mcp/paraview_mcp_server.py"
        ]
      }
    }
```

## running 

### 1. Start paraview server

```shell
python pvserver --multi-clients
```

### 2. Connect to paraview server from paraview GUI (file -> connect)

### 3. Start claude desktop app 



### 4. (Optional) Auto approve MCP calls (use with caution)


Enable dev tool:
https://modelcontextprotocol.io/docs/tools/debugging#using-chrome-devtools

Code snippet originally from: https://gist.github.com/RafalWilinski/3416a497f94ee2a0c589a8d930304950

```javascript
// HOW TO INSTRUCTIONS
// 1. Open Claude Desktop
// 2. Enable Chrome DevTool (on mac use "Command-Option-Shift-i"), two DevTool Window will be open
// 3. Navigate to Developer Tools window named "Developer Tools - https://claude.ai"
// 4. Go to "Console" tab
// 5. Type "allow pasting" and hit Enter
// 6. Paste this snippet and hit Enter

// From now on, all MCP calls will be auto-approved

// END INSTRUCTIONS

// Cooldown tracking
let lastClickTime = 0;
const COOLDOWN_MS = 2000; // 2 seconds cooldown is fast enough

const observer = new MutationObserver((mutations) => {
  // Check if we're still in cooldown
  const now = Date.now();
  if (now - lastClickTime < COOLDOWN_MS) {
    console.log("🕒 Still in cooldown period, skipping...");
    return;
  }

  console.log("🔍 Checking mutations...");

  const dialog = document.querySelector('[role="dialog"]');
  if (!dialog) return;

  const buttonWithDiv = dialog.querySelector("button div");
  if (!buttonWithDiv) return;

  const toolText = buttonWithDiv.textContent;
  if (!toolText) return;

  console.log("📝 Found tool request:", toolText);

  const toolName = toolText.match(/Run (\S+) from/)?.[1];
  if (!toolName) return;

  console.log("🛠️ Tool name:", toolName);

  const allowButton = Array.from(dialog.querySelectorAll("button")).find(
    (button) => button.textContent.toLowerCase().includes("allow for this chat") // case insensitive checking fixes the original script
  );

  if (allowButton) {
    console.log("🚀 Auto-approving tool:", toolName);
    lastClickTime = now; // Set cooldown
    allowButton.click();
  }
});

// Start observing
observer.observe(document.body, {
  childList: true,
  subtree: true,
});
```

***

## Citing Paraview_MCP

S. Liu, H. Miao, and P.-T. Bremer, “Paraview-MCP: Autonomous Visualization Agents with Direct Tool Use,” in Proc. IEEE VIS 2025 Short Papers, 2025, pp. 00

```bibtex
@inproceedings{liu2025paraview,
  title={Paraview-MCP: Autonomous Visualization Agents with Direct Tool Use},
  author={Liu, S. and Miao, H. and Bremer, P.-T.},
  booktitle={Proc. IEEE VIS 2025 Short Papers},
  pages={00},
  year={2025},
  organization={IEEE}
}
```

## Authors 
Paraview_MCP was created by Shusen Liu (liu42@llnl.gov) and Haichao Miao (miao1@llnl.gov)

## License
Paraview_MCP is distributed under the terms of the BSD-3 license.

LLNL-CODE-2007260
