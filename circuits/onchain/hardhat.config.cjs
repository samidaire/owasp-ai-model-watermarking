require("@nomicfoundation/hardhat-ethers");
/** Local, in-process EVM only: nothing is deployed to a public network. */
module.exports = {
  solidity: { version: "0.8.24", settings: { optimizer: { enabled: true, runs: 200 } } },
  networks: { hardhat: { chainId: 31337 } },
};
